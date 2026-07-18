"""Scheduler leader election: single replica runs background loops."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import TYPE_CHECKING

from sqlalchemy import text

import spectra_scheduler.locking as _sched_lock
from spectra_persistence.database import advisory_lock_connection
from spectra_scheduler import async_ops
from spectra_scheduler.locks import _SCHEDULER_LEADER_LOCK_ID

if TYPE_CHECKING:
    from spectra_scheduler.service import SchedulerService

logger = logging.getLogger("spectra_scheduler")


async def _watch_leader_connection(lock_owner, scheduler: SchedulerService) -> None:
    """Stop the active scheduler if its advisory-lock connection is lost."""
    while scheduler.running:
        await async_ops.sleep(10)
        try:
            await lock_owner.execute(text("SELECT 1"))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduler leader connection lost; relinquishing leadership")
            await scheduler.stop()
            return


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
                    watchdog = asyncio.create_task(
                        _watch_leader_connection(lock_owner, scheduler), name="leader_connection_watchdog"
                    )
                    try:
                        await scheduler.start()
                    finally:
                        watchdog.cancel()
                        with suppress(asyncio.CancelledError):
                            await watchdog
                    if not getattr(scheduler, "running", False):
                        return
                    logger.error("Scheduler start returned unexpectedly; re-electing after backoff")
                    await async_ops.sleep(5)
            # Not leader — stand by
            logger.info("Another scheduler is leader, standing by...")
            await async_ops.sleep(15)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Leader election error — retrying in 15s")
            await async_ops.sleep(15)
