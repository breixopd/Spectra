"""Scheduler leader election: single replica runs background loops."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import spectra_scheduler.locking as _sched_lock
from spectra_platform.core.database import advisory_lock_connection
from spectra_scheduler import async_ops
from spectra_scheduler.locks import _SCHEDULER_LEADER_LOCK_ID

if TYPE_CHECKING:
    from spectra_scheduler.service import SchedulerService

logger = logging.getLogger("spectra_scheduler")


async def leader_election_loop(scheduler: SchedulerService) -> None:
    """Try to acquire the global scheduler leader lock; stand by if another replica holds it."""
    while True:
        try:
            async with _sched_lock.advisory_lock_owner(
                _SCHEDULER_LEADER_LOCK_ID,
                connection_factory=advisory_lock_connection,
            ) as lock_owner:
                if lock_owner is not None:
                    logger.info("Scheduler acquired leader lock — starting tasks")
                    await scheduler.start()
                    return  # start() runs until stopped
            # Not leader — stand by
            logger.info("Another scheduler is leader, standing by...")
            await async_ops.sleep(15)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Leader election error — retrying in 15s")
            await async_ops.sleep(15)
