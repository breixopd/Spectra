"""Concurrent micro-task orchestration with dependency and retry safety.

The orchestrator deliberately keeps task execution bounded: every task is
scope-checked before launch, dependency failures are propagated as skips, and
timeouts/cancellation are represented in the result rather than silently
turning into successful work.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from spectra_mission.coordination.scope_enforcer import ScopeEnforcer
from spectra_mission.coordination.task_decomposer import MicroTask

logger = logging.getLogger(__name__)


class TaskExecStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"  # Scope check failed
    SKIPPED = "skipped"  # Dependency could not be satisfied
    CANCELLED = "cancelled"  # Explicit cancellation, never retried


@dataclass
class TaskExecRecord:
    """Execution record for a single micro-task."""

    task: MicroTask
    status: TaskExecStatus = TaskExecStatus.PENDING
    started_at: float = 0.0
    completed_at: float = 0.0
    result: Any = None
    error: str = ""
    retries: int = 0
    blocked_reason: str = ""


@dataclass
class OrchestrationResult:
    """Result of running a batch of micro-tasks."""

    records: list[TaskExecRecord]
    completed: int = 0
    failed: int = 0
    blocked: int = 0
    total_duration_seconds: float = 0.0
    skipped: int = 0
    cancelled: int = 0

    @property
    def all_successful(self) -> bool:
        """Return true only when every supplied task completed successfully."""

        # Empty batches are a useful no-op and retain the historical result.
        if not self.records:
            return True
        return self.completed == len(self.records)


class Orchestrator:
    """Coordinate execution of micro-tasks with dependency management."""

    def __init__(
        self,
        scope_enforcer: ScopeEnforcer,
        tool_executor: Callable[..., Any] | None = None,
        *,
        max_concurrency: int = 3,
        retry_base_delay: float = 2.0,
    ):
        self.scope_enforcer = scope_enforcer
        self.tool_executor = tool_executor
        self.max_concurrency = max(1, min(int(max_concurrency), 64))
        self.retry_base_delay = max(0.0, float(retry_base_delay))
        self._semaphore = asyncio.Semaphore(self.max_concurrency)

    async def execute(
        self,
        tasks: list[MicroTask],
        *,
        progress_callback: Callable[[TaskExecRecord], Any] | None = None,
        stop_on_failure: bool = False,
    ) -> OrchestrationResult:
        """Execute tasks respecting dependencies and bounded retries."""

        if not tasks:
            return OrchestrationResult(records=[], total_duration_seconds=0)

        task_ids = [task.id for task in tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("Micro-task IDs must be unique within an orchestration batch")

        start_time = time.monotonic()

        # Validate each task against its own phase.  A batch can contain tasks
        # generated for different phases after a replan.
        phase = tasks[0].phase or "discovery"
        blocked_reasons = self._scope_check_all(tasks, phase)

        records: dict[str, TaskExecRecord] = {task.id: TaskExecRecord(task=task) for task in tasks}
        completed_ids: set[str] = set()
        failed_ids: set[str] = set()
        skipped_ids: set[str] = set()
        cancelled_ids: set[str] = set()

        for task_id, reason in blocked_reasons.items():
            record = records[task_id]
            record.status = TaskExecStatus.BLOCKED
            record.blocked_reason = reason
            failed_ids.add(task_id)
            await self._notify_progress(record, progress_callback)

        if stop_on_failure and failed_ids:
            # Scope violations are failures discovered before launch; honor
            # the same stop contract as a runtime failure.
            for task in tasks:
                if task.id in failed_ids:
                    continue
                record = records[task.id]
                record.status = TaskExecStatus.SKIPPED
                record.blocked_reason = "stop_on_failure after scope block"
                skipped_ids.add(task.id)
                await self._notify_progress(record, progress_callback)

        while len(completed_ids | failed_ids | skipped_ids | cancelled_ids) < len(tasks):
            ready = self._get_ready_tasks(
                tasks,
                completed_ids,
                failed_ids,
                records,
                skipped=skipped_ids,
                cancelled=cancelled_ids,
            )

            if not ready:
                # No runnable task means an unresolved dependency, a missing
                # dependency, or a cycle.  Mark all remaining work skipped so
                # the result cannot be mistaken for a successful no-op.
                resolved = completed_ids | failed_ids | skipped_ids | cancelled_ids
                for task in tasks:
                    if task.id in resolved:
                        continue
                    record = records[task.id]
                    dependency_failures = [
                        dep_id
                        for dep_id in task.depends_on
                        if dep_id in failed_ids
                        or dep_id in skipped_ids
                        or dep_id in cancelled_ids
                        or (
                            dep_id in records
                            and records[dep_id].status
                            in {
                                TaskExecStatus.FAILED,
                                TaskExecStatus.BLOCKED,
                                TaskExecStatus.SKIPPED,
                                TaskExecStatus.CANCELLED,
                            }
                        )
                    ]
                    if dependency_failures:
                        reason = f"dependency failed or skipped: {', '.join(dependency_failures)}"
                    else:
                        missing = [dep_id for dep_id in task.depends_on if dep_id not in records]
                        suffix = f" (missing: {', '.join(missing)})" if missing else ""
                        reason = f"dependency deadlock{suffix}"
                    record.status = TaskExecStatus.SKIPPED
                    record.blocked_reason = reason
                    skipped_ids.add(task.id)
                    await self._notify_progress(record, progress_callback)
                break

            try:
                results = await asyncio.gather(
                    *(self._execute_one(records[task.id], progress_callback) for task in ready),
                    return_exceptions=True,
                )
            except asyncio.CancelledError:
                # Preserve caller cancellation while accurately closing records
                # that never reached the task-level cancellation handler.
                for record in records.values():
                    if record.status in (TaskExecStatus.PENDING, TaskExecStatus.RUNNING):
                        record.status = TaskExecStatus.CANCELLED
                        record.error = "orchestration cancelled"
                        record.completed_at = time.monotonic()
                raise

            for result in results:
                if isinstance(result, BaseException):
                    logger.warning("Orchestrator task terminated with %s", type(result).__name__)

            failed_this_round = False
            for task in ready:
                record = records[task.id]
                if record.status == TaskExecStatus.COMPLETED:
                    completed_ids.add(task.id)
                elif record.status in (TaskExecStatus.FAILED, TaskExecStatus.BLOCKED):
                    failed_ids.add(task.id)
                    failed_this_round = True
                elif record.status == TaskExecStatus.CANCELLED:
                    cancelled_ids.add(task.id)
                    failed_this_round = True

            if stop_on_failure and failed_this_round:
                resolved = completed_ids | failed_ids | skipped_ids | cancelled_ids
                for task in tasks:
                    if task.id in resolved:
                        continue
                    record = records[task.id]
                    record.status = TaskExecStatus.SKIPPED
                    record.blocked_reason = "stop_on_failure after task failure"
                    skipped_ids.add(task.id)
                    await self._notify_progress(record, progress_callback)
                break

        duration = time.monotonic() - start_time
        result = OrchestrationResult(
            records=list(records.values()),
            completed=sum(1 for record in records.values() if record.status == TaskExecStatus.COMPLETED),
            failed=sum(1 for record in records.values() if record.status == TaskExecStatus.FAILED),
            blocked=sum(1 for record in records.values() if record.status == TaskExecStatus.BLOCKED),
            skipped=sum(1 for record in records.values() if record.status == TaskExecStatus.SKIPPED),
            cancelled=sum(1 for record in records.values() if record.status == TaskExecStatus.CANCELLED),
            total_duration_seconds=round(duration, 2),
        )
        logger.info(
            "Orchestration complete: %d tasks (%d ok, %d failed, %d blocked, %d skipped, %d cancelled) in %.2fs",
            len(tasks),
            result.completed,
            result.failed,
            result.blocked,
            result.skipped,
            result.cancelled,
            duration,
        )
        return result

    # ── Internal execution ────────────────────────────────────────────

    async def _execute_one(
        self,
        record: TaskExecRecord,
        progress_callback: Callable[[TaskExecRecord], Any] | None = None,
    ) -> None:
        """Execute one task with retry, timeout, and cancellation handling."""

        task = record.task
        if record.status in (TaskExecStatus.BLOCKED, TaskExecStatus.SKIPPED, TaskExecStatus.CANCELLED):
            return

        async with self._semaphore:
            for attempt in range(task.max_retries + 1):
                timeout_seconds = task.timeout_seconds
                if timeout_seconds is None:
                    timeout_seconds = task.metadata.get("timeout_seconds", task.metadata.get("timeout"))
                if timeout_seconds is not None:
                    timeout_seconds = float(timeout_seconds)
                    if timeout_seconds <= 0:
                        record.status = TaskExecStatus.FAILED
                        record.error = "task timeout must be greater than zero"
                        record.completed_at = time.monotonic()
                        await self._notify_progress(record, progress_callback)
                        return
                try:
                    record.status = TaskExecStatus.RUNNING
                    if record.started_at == 0.0:
                        record.started_at = time.monotonic()
                    attempt_result = self._invoke_executor(task)
                    if timeout_seconds is not None:
                        record.result = await asyncio.wait_for(attempt_result, timeout=float(timeout_seconds))
                    else:
                        record.result = await attempt_result
                    record.status = TaskExecStatus.COMPLETED
                    record.completed_at = time.monotonic()
                    break
                except asyncio.CancelledError:
                    # Cancellation is a control signal, never a retryable
                    # tool error.  Preserve and propagate it through gather.
                    record.status = TaskExecStatus.CANCELLED
                    record.error = "task cancelled"
                    record.completed_at = time.monotonic()
                    await self._notify_progress(record, progress_callback)
                    raise
                except TimeoutError:
                    record.error = f"task timed out after {timeout_seconds}s"
                    record.retries = attempt + 1
                    if attempt < task.max_retries:
                        delay = self.retry_base_delay * (2**attempt)
                        logger.warning(
                            "Task %s timed out (attempt %d/%d), retrying in %.1fs",
                            task.id,
                            attempt + 1,
                            task.max_retries,
                            delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        record.status = TaskExecStatus.FAILED
                        record.completed_at = time.monotonic()
                        logger.error("Task %s timed out after %d retries", task.id, task.max_retries)
                except Exception as exc:
                    record.error = str(exc)
                    record.retries = attempt + 1
                    if attempt < task.max_retries:
                        delay = self.retry_base_delay * (2**attempt)
                        logger.warning(
                            "Task %s failed (attempt %d/%d), retrying in %.1fs: %s",
                            task.id,
                            attempt + 1,
                            task.max_retries,
                            delay,
                            exc,
                        )
                        await asyncio.sleep(delay)
                    else:
                        record.status = TaskExecStatus.FAILED
                        record.completed_at = time.monotonic()
                        logger.error("Task %s failed after %d retries: %s", task.id, task.max_retries, exc)

        await self._notify_progress(record, progress_callback)

    async def _invoke_executor(self, task: MicroTask) -> Any:
        """Invoke either a synchronous or asynchronous executor uniformly."""

        if self.tool_executor:
            # Synchronous adapters are common for deterministic test tools and
            # legacy plugins. Run them off-loop so task timeouts and sibling
            # cancellation remain effective even if the adapter blocks.
            if inspect.iscoroutinefunction(self.tool_executor):
                return await self.tool_executor(task.tool_name, task.tool_args)
            result = await asyncio.to_thread(self.tool_executor, task.tool_name, task.tool_args)
            if inspect.isawaitable(result):
                return await result
            return result

        # No executor — simulate for tests and local dry runs.
        await asyncio.sleep(0.01)
        return {"status": "ok", "tool": task.tool_name}

    async def _notify_progress(
        self,
        record: TaskExecRecord,
        progress_callback: Callable[[TaskExecRecord], Any] | None,
    ) -> None:
        """Call a sync/async progress hook without affecting task outcome."""

        if not progress_callback:
            return
        try:
            callback_result = progress_callback(record)
            if inspect.isawaitable(callback_result):
                await callback_result
        except Exception:
            logger.exception("Progress callback failed for task %s", record.task.id)

    # ── Dependency resolution ─────────────────────────────────────────

    def _get_ready_tasks(
        self,
        all_tasks: list[MicroTask],
        completed: set[str],
        failed: set[str],
        records: dict[str, TaskExecRecord],
        *,
        skipped: set[str] | None = None,
        cancelled: set[str] | None = None,
    ) -> list[MicroTask]:
        """Get tasks whose dependencies are all satisfied and not executed."""

        ready: list[MicroTask] = []
        done = completed | failed | (skipped or set()) | (cancelled or set())
        for task in all_tasks:
            if task.id in done:
                continue
            if records[task.id].status in {
                TaskExecStatus.BLOCKED,
                TaskExecStatus.SKIPPED,
                TaskExecStatus.CANCELLED,
            }:
                continue
            if all(dep_id in completed for dep_id in task.depends_on):
                ready.append(task)

        ready.sort(key=lambda task: (task.priority, task.id))
        return ready

    # ── Scope validation ──────────────────────────────────────────────

    def _scope_check_all(self, tasks: list[MicroTask], phase: str) -> dict[str, str]:
        """Pre-validate tasks, using each task's own phase when available."""

        blocked: dict[str, str] = {}
        for task in tasks:
            task_phase = task.phase or phase
            verdict = self.scope_enforcer.validate(
                f"{task.tool_name} {task.tool_args}", task.technique_category, task_phase
            )
            if not verdict.allowed:
                blocked[task.id] = verdict.blocked_by
                logger.warning("Task %s blocked: %s", task.id, verdict.blocked_by)
        return blocked
