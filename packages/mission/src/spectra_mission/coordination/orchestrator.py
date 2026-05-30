"""Orchestrator — manages concurrent micro-task execution with dependency ordering.

Key responsibilities:
- Order tasks by dependencies (DAG topological sort)
- Execute independent tasks concurrently
- Serialize dependent tasks (exploit chains, credential testing)
- Retry failed micro-tasks with backoff
- Track task execution status for progress reporting
- Integrate with ScopeEnforcer for pre-execution validation
"""

from __future__ import annotations

import asyncio
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
    SKIPPED = "skipped"


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

    @property
    def all_successful(self) -> bool:
        return self.failed == 0 and self.blocked == 0


class Orchestrator:
    """Coordinates execution of micro-tasks with dependency management.

    Usage:
        orchestrator = Orchestrator(scope_enforcer, tool_executor)
        tasks = decomposer.decompose(plan_task, phase)
        result = await orchestrator.execute(tasks)
    """

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
        self.max_concurrency = max_concurrency
        self.retry_base_delay = retry_base_delay
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def execute(
        self,
        tasks: list[MicroTask],
        *,
        progress_callback: Callable[[TaskExecRecord], Any] | None = None,
        stop_on_failure: bool = False,
    ) -> OrchestrationResult:
        """Execute a list of micro-tasks respecting dependencies and concurrency.

        Args:
            tasks: Micro-tasks to execute
            progress_callback: Called after each task completes/fails
            stop_on_failure: If True, stop all tasks on first failure

        Returns:
            OrchestrationResult with execution records and summary
        """
        if not tasks:
            return OrchestrationResult(records=[], total_duration_seconds=0)

        start_time = time.monotonic()

        # Pre-pass: scope check all tasks against current phase
        phase = tasks[0].phase if tasks else "discovery"
        self._scope_check_all(tasks, phase)

        # Build dependency graph
        records: dict[str, TaskExecRecord] = {t.id: TaskExecRecord(task=t) for t in tasks}
        completed_ids: set[str] = set()
        failed_ids: set[str] = set()

        # Execute layer by layer (tasks with no pending dependencies)
        while len(completed_ids) + len(failed_ids) < len(tasks):
            ready = self._get_ready_tasks(tasks, completed_ids, failed_ids, records)

            if not ready:
                # Deadlock detected — remaining tasks have unresolvable dependencies
                remaining = {t.id for t in tasks} - completed_ids - failed_ids
                for rid in remaining:
                    records[rid].status = TaskExecStatus.SKIPPED
                break

            # Execute ready tasks concurrently
            results = await asyncio.gather(
                *[self._execute_one(records[t.id], progress_callback) for t in ready],
                return_exceptions=True,
            )

            for result in results:
                if isinstance(result, Exception):
                    logger.error("Orchestrator task raised: %s", result)
                    continue

            # Update completed/failed sets
            for t in ready:
                rec = records[t.id]
                if rec.status == TaskExecStatus.COMPLETED:
                    completed_ids.add(t.id)
                elif rec.status in (TaskExecStatus.FAILED, TaskExecStatus.BLOCKED):
                    failed_ids.add(t.id)
                    if stop_on_failure:
                        # Cancel remaining
                        for remaining in tasks:
                            if remaining.id not in completed_ids | failed_ids:
                                records[remaining.id].status = TaskExecStatus.SKIPPED
                        break

        duration = time.monotonic() - start_time

        result = OrchestrationResult(
            records=list(records.values()),
            completed=sum(1 for r in records.values() if r.status == TaskExecStatus.COMPLETED),
            failed=sum(1 for r in records.values() if r.status == TaskExecStatus.FAILED),
            blocked=sum(1 for r in records.values() if r.status == TaskExecStatus.BLOCKED),
            total_duration_seconds=round(duration, 2),
        )

        logger.info(
            "Orchestration complete: %d tasks (%d ok, %d failed, %d blocked) in %.2fs",
            len(tasks), result.completed, result.failed, result.blocked, duration,
        )
        return result

    # ── Internal execution ────────────────────────────────────────────

    async def _execute_one(
        self,
        record: TaskExecRecord,
        progress_callback: Callable | None = None,
    ) -> None:
        """Execute a single micro-task with retry logic."""
        task = record.task

        if record.status == TaskExecStatus.BLOCKED:
            return

        async with self._semaphore:
            for attempt in range(task.max_retries + 1):
                try:
                    record.status = TaskExecStatus.RUNNING
                    record.started_at = time.monotonic()

                    if self.tool_executor:
                        record.result = await self.tool_executor(task.tool_name, task.tool_args)
                    else:
                        # No executor — simulate for testing
                        await asyncio.sleep(0.01)
                        record.result = {"status": "ok", "tool": task.tool_name}

                    record.status = TaskExecStatus.COMPLETED
                    record.completed_at = time.monotonic()
                    break

                except Exception as exc:
                    record.error = str(exc)
                    record.retries = attempt + 1

                    if attempt < task.max_retries:
                        delay = self.retry_base_delay * (2 ** attempt)
                        logger.warning(
                            "Task %s failed (attempt %d/%d), retrying in %.1fs: %s",
                            task.id, attempt + 1, task.max_retries, delay, exc,
                        )
                        await asyncio.sleep(delay)
                    else:
                        record.status = TaskExecStatus.FAILED
                        record.completed_at = time.monotonic()
                        logger.error("Task %s failed after %d retries: %s", task.id, task.max_retries, exc)

        if progress_callback:
            try:
                progress_callback(record)
            except Exception:
                logger.exception("Progress callback failed for task %s", task.id)

    # ── Dependency resolution ─────────────────────────────────────────

    def _get_ready_tasks(
        self,
        all_tasks: list[MicroTask],
        completed: set[str],
        failed: set[str],
        records: dict[str, TaskExecRecord],
    ) -> list[MicroTask]:
        """Get tasks whose dependencies are all satisfied and haven't been executed."""
        ready: list[MicroTask] = []
        done = completed | failed

        for task in all_tasks:
            if task.id in done:
                continue
            if records[task.id].status == TaskExecStatus.BLOCKED:
                continue

            deps_satisfied = all(
                dep_id in completed for dep_id in task.depends_on
            )
            if deps_satisfied:
                ready.append(task)

        # Sort by priority (lower = higher priority)
        ready.sort(key=lambda t: (t.priority, t.id))
        return ready

    # ── Scope validation ──────────────────────────────────────────────

    def _scope_check_all(self, tasks: list[MicroTask], phase: str) -> None:
        """Pre-validate all tasks against scope/framework constraints."""
        for task in tasks:
            verdict = self.scope_enforcer.validate(
                action=f"{task.tool_name} {task.tool_args}",
                technique_category=task.technique_category,
                phase=phase,
            )
            if not verdict.allowed:
                task.blocked_reason = verdict.blocked_by
                logger.warning("Task %s blocked: %s", task.id, verdict.blocked_by)
