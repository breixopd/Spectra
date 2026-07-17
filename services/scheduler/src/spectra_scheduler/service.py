"""SchedulerService — composes mixin loop implementations and orchestrates asyncio tasks."""

import asyncio
import logging

from spectra_common.tasks import create_safe_task
from spectra_scheduler import async_ops
from spectra_scheduler.locks import _SCHEDULER_TASK_SPECS
from spectra_scheduler.loops.core_loops import SchedulerCoreLoopsMixin
from spectra_scheduler.loops.db_maintenance import SchedulerDbMaintenanceMixin
from spectra_scheduler.loops.docker_maintenance import SchedulerDockerMaintenanceMixin
from spectra_scheduler.loops.infra_monitor import SchedulerInfraMonitorMixin

logger = logging.getLogger("spectra_scheduler")


class SchedulerService(
    SchedulerCoreLoopsMixin,
    SchedulerDbMaintenanceMixin,
    SchedulerInfraMonitorMixin,
    SchedulerDockerMaintenanceMixin,
):
    """Manages periodic background tasks."""

    def __init__(self):
        self.running = False
        self.tasks: list[asyncio.Task] = []
        self._named_tasks: dict[str, asyncio.Task] = {}
        self._task_restarts: dict[str, int] = {}
        self._task_last_failure: dict[str, str] = {}

    async def _supervise_task(self, task_name: str, method_name: str) -> None:
        """Keep a scheduler loop alive after an unexpected return or exception.

        Managed loops are expected to run until ``self.running`` becomes false.
        Restarting a failed loop in-process avoids a healthy scheduler container
        silently losing a maintenance responsibility. The bounded exponential
        delay prevents tight crash loops from overwhelming dependencies.
        """
        failures = 0
        while self.running:
            failure = "returned unexpectedly"
            try:
                await getattr(self, method_name)()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failure = f"{type(exc).__name__}: {exc}"
                logger.exception("Scheduler task '%s' crashed", task_name)

            if not self.running:
                break

            failures += 1
            self._task_restarts[task_name] = failures
            self._task_last_failure[task_name] = failure
            delay = min(5 * (2 ** min(failures - 1, 6)), 300)
            logger.error(
                "Scheduler task '%s' %s; restarting in %ss (attempt %d)",
                task_name,
                failure,
                delay,
                failures,
            )
            await async_ops.sleep(delay)

    async def start(self):
        self.running = True
        logger.info("Scheduler service starting...")

        self._named_tasks = {
            task_name: create_safe_task(self._supervise_task(task_name, method_name), name=task_name)
            for task_name, method_name in _SCHEDULER_TASK_SPECS
        }
        self.tasks = list(self._named_tasks.values())

        logger.info("Scheduler running with %d tasks", len(self.tasks))
        task_names = list(self._named_tasks.keys())
        results = await async_ops.gather(*self.tasks, return_exceptions=True)
        for task_name, result in zip(task_names, results or [], strict=False):
            if isinstance(result, Exception):
                logger.error("Scheduler task '%s' failed: %s", task_name, result, exc_info=result)

    async def stop(self):
        self.running = False
        for task in self.tasks:
            task.cancel()
        logger.info("Scheduler stopped")

    def health(self) -> dict:
        task_status = {}
        for task_name, _method_name in _SCHEDULER_TASK_SPECS:
            task = self._named_tasks.get(task_name)
            if task is None:
                task_status[task_name] = "missing"
            elif task.done():
                task_status[task_name] = "dead"
            elif task_name in self._task_restarts:
                task_status[task_name] = "recovering"
            else:
                task_status[task_name] = "alive"

        if not self.running:
            svc_status = "standby"
        elif any(state != "alive" for state in task_status.values()):
            svc_status = "degraded"
        else:
            svc_status = "healthy"
        return {
            "status": svc_status,
            "tasks": task_status,
            "running": self.running,
            "restart_counts": dict(self._task_restarts),
            "last_failures": dict(self._task_last_failure),
        }
