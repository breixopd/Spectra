"""Background task loops for system maintenance.

Extracted from lifespan.py to reduce module size and improve testability.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from spectra_common.constants import CACHE_CLEANUP_INTERVAL, SYSTEM_CLEANUP_INTERVAL
from app.core.database import async_session_maker

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


async def cache_cleanup_loop() -> None:
    """Periodically purge expired cache entries."""
    from app.infrastructure.cache import get_cache

    logger.info("Cache cleanup task started (interval=%ds)", CACHE_CLEANUP_INTERVAL)
    while True:
        try:
            await asyncio.sleep(CACHE_CLEANUP_INTERVAL)
            cache = get_cache()
            if cache:
                removed = await cache.purge_expired()
                if removed:
                    logger.info("Cache cleanup: purged %d expired entries", removed)
        except asyncio.CancelledError:
            logger.info("Cache cleanup task stopped")
            break
        except (OSError, RuntimeError) as e:
            logger.error("Cache cleanup error: %s", e)


async def periodic_cleanup_loop() -> None:
    """Periodically run system maintenance cleanup tasks."""
    logger.info("System cleanup task started (interval=%ds)", SYSTEM_CLEANUP_INTERVAL)
    while True:
        try:
            await asyncio.sleep(SYSTEM_CLEANUP_INTERVAL)
            from app.services.maintenance import run_all_cleanup

            await run_all_cleanup()
        except asyncio.CancelledError:
            logger.info("System cleanup task stopped")
            break
        except (OSError, RuntimeError) as e:
            logger.error("System cleanup error: %s", e)


async def sandbox_watchdog_loop() -> None:
    """Periodically check sandbox heartbeats and reap stale ones."""
    from app.models.infrastructure import Sandbox
    from app.services.tools.sandbox import get_sandbox_pool

    logger.info("Sandbox watchdog started (idle_timeout=%ds)", settings.SANDBOX_IDLE_TIMEOUT)
    while True:
        try:
            await asyncio.sleep(60)
            pool = get_sandbox_pool()
            if not pool or not pool.available:
                continue

            async with async_session_maker() as session:
                result = await session.execute(select(Sandbox).where(Sandbox.status == "running"))
                sandboxes = list(result.scalars().all())

            now = datetime.now(UTC)
            for sb in sandboxes:
                age = (now - sb.created_at).total_seconds()
                if age < settings.SANDBOX_HEARTBEAT_INTERVAL * 2:
                    continue

                idle_seconds = (now - sb.last_heartbeat).total_seconds() if sb.last_heartbeat else age

                if idle_seconds > settings.SANDBOX_IDLE_TIMEOUT:
                    logger.warning(
                        "Watchdog: reaping stale sandbox %s (mission=%s, idle=%.0fs)",
                        sb.container_name,
                        sb.mission_id[:8],
                        idle_seconds,
                    )
                    await pool.destroy(sb.mission_id)

        except asyncio.CancelledError:
            logger.info("Sandbox watchdog stopped")
            break
        except (OSError, RuntimeError, SQLAlchemyError) as e:
            logger.error("Sandbox watchdog error: %s", e)
