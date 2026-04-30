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

    async def start(self):
        self.running = True
        logger.info("Scheduler service starting...")

        self._named_tasks = {
            task_name: create_safe_task(getattr(self, method_name)(), name=task_name)
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
        }
