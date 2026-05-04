"""Schedules background work: re-exports `app` for uvicorn and `main` for the CLI."""

from __future__ import annotations

import asyncio
import logging
import signal

from spectra_scheduler.leader import leader_election_loop as _leader_election_loop
from spectra_scheduler.locks import (
    _BACKUP_LOCK_ID,
    _CACHE_CLEANUP_LOCK_ID,
    _CAPACITY_MONITOR_LOCK_ID,
    _DB_MAINTENANCE_LOCK_ID,
    _DISK_MONITOR_LOCK_ID,
    _DOCKER_CLEANUP_LOCK_ID,
    _EXPLOIT_REFRESH_LOCK_ID,
    _HEALTH_REPORTER_LOCK_ID,
    _IMAGE_UPDATE_LOCK_ID,
    _INFRA_MONITOR_LOCK_ID,
    _METRICS_COLLECTOR_LOCK_ID,
    _PERIODIC_CLEANUP_LOCK_ID,
    _QUOTA_LOCK_ID,
    _SANDBOX_WATCHDOG_LOCK_ID,
    _SCHEDULER_LEADER_LOCK_ID,
    _SCHEDULER_TASK_SPECS,
    _STALE_JOB_LOCK_ID,
)
from spectra_scheduler.routes import app, health, lifespan
from spectra_scheduler.service import SchedulerService

__all__ = [
    "_BACKUP_LOCK_ID",
    "_CACHE_CLEANUP_LOCK_ID",
    "_CAPACITY_MONITOR_LOCK_ID",
    "_DB_MAINTENANCE_LOCK_ID",
    "_DISK_MONITOR_LOCK_ID",
    "_DOCKER_CLEANUP_LOCK_ID",
    "_EXPLOIT_REFRESH_LOCK_ID",
    "_HEALTH_REPORTER_LOCK_ID",
    "_IMAGE_UPDATE_LOCK_ID",
    "_INFRA_MONITOR_LOCK_ID",
    "_METRICS_COLLECTOR_LOCK_ID",
    "_PERIODIC_CLEANUP_LOCK_ID",
    "_QUOTA_LOCK_ID",
    "_SANDBOX_WATCHDOG_LOCK_ID",
    "_SCHEDULER_LEADER_LOCK_ID",
    "_SCHEDULER_TASK_SPECS",
    "_STALE_JOB_LOCK_ID",
    "SchedulerService",
    "_leader_election_loop",
    "app",
    "health",
    "lifespan",
    "main",
]


async def main():
    scheduler = SchedulerService()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(scheduler.stop()))

    await scheduler.start()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    asyncio.run(main())
