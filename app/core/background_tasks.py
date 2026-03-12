"""Background loop tasks for Spectra lifespan management."""

import asyncio
import logging
from datetime import datetime

from app.core.config import settings
from app.core.telemetry import telemetry

logger = logging.getLogger("spectra.lifespan")

# Mission timeout check interval — every 15 minutes
_MISSION_TIMEOUT_INTERVAL = 900

# Daily maintenance interval — every 24 hours
_DAILY_MAINTENANCE_INTERVAL = 86400

# Interval for cache cleanup (seconds) — every 10 minutes
_CACHE_CLEANUP_INTERVAL = 600


async def cache_cleanup_loop() -> None:
    """Periodically purge expired cache entries."""
    from app.core.cache import get_cache

    logger.info("Cache cleanup task started (interval=%ds)", _CACHE_CLEANUP_INTERVAL)
    while True:
        try:
            await asyncio.sleep(_CACHE_CLEANUP_INTERVAL)
            cache = get_cache()
            if cache:
                removed = await cache.purge_expired()
                if removed:
                    logger.info("Cache cleanup: purged %d expired entries", removed)
        except asyncio.CancelledError:
            logger.info("Cache cleanup task stopped")
            break
        except Exception as e:
            logger.error("Cache cleanup error: %s", e)


# Interval for system cleanup (seconds) — every hour
_SYSTEM_CLEANUP_INTERVAL = 3600


async def periodic_cleanup_loop() -> None:
    """Periodically run system maintenance cleanup tasks."""
    logger.info("System cleanup task started (interval=%ds)", _SYSTEM_CLEANUP_INTERVAL)
    while True:
        try:
            await asyncio.sleep(_SYSTEM_CLEANUP_INTERVAL)
            from app.worker.cleanup_jobs import run_all_cleanup

            await run_all_cleanup()
        except asyncio.CancelledError:
            logger.info("System cleanup task stopped")
            break
        except Exception as e:
            logger.error("System cleanup error: %s", e)


_RESOURCE_COLLECT_INTERVAL = 15  # seconds


async def resource_collection_loop() -> None:
    """Periodically collect system resource metrics (CPU, memory, GC)."""
    logger.info("Resource collection started (interval=%ds)", _RESOURCE_COLLECT_INTERVAL)
    while True:
        try:
            await asyncio.sleep(_RESOURCE_COLLECT_INTERVAL)
            telemetry.collect_system_resources()
        except asyncio.CancelledError:
            logger.info("Resource collection stopped")
            break
        except Exception as e:
            logger.error("Resource collection error: %s", e)


async def sandbox_watchdog_loop() -> None:
    """Periodically check sandbox heartbeats and reap stale ones."""
    from datetime import UTC, datetime

    from sqlalchemy import select

    from app.core.database import async_session_maker
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

                if sb.last_heartbeat:
                    idle_seconds = (now - sb.last_heartbeat).total_seconds()
                else:
                    idle_seconds = age

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
        except Exception as e:
            logger.error("Sandbox watchdog error: %s", e)


async def set_system_status(status: str, message: str) -> None:
    """Update system status in cache for UI polling."""
    try:
        from app.core.cache import get_cache

        cache = get_cache()
        if cache:
            await cache.set(
                "spectra:system:status",
                {
                    "status": status,
                    "message": message,
                    "timestamp": datetime.now().isoformat(),
                },
                ttl=3600,
            )
    except Exception as e:
        logger.debug("Failed to set system status: %s", e)


async def add_system_operation(op_id: str, op_type: str, desc: str) -> None:
    """Add an ongoing operation to the system status."""
    try:
        from app.core.cache import get_cache

        cache = get_cache()
        if cache:
            op = {
                "id": op_id,
                "type": op_type,
                "description": desc,
                "started_at": datetime.now().isoformat(),
            }
            await cache.set(f"spectra:system:operations:{op_id}", op, ttl=3600)
    except Exception as e:
        logger.debug("Failed to add system operation: %s", e)


async def remove_system_operation(op_id: str) -> None:
    """Remove a completed operation."""
    try:
        from app.core.cache import get_cache

        cache = get_cache()
        if cache:
            await cache.delete(f"spectra:system:operations:{op_id}")
    except Exception as e:
        logger.debug("Failed to remove system operation: %s", e)


async def mission_timeout_loop() -> None:
    """Periodically check for and time out long-running missions."""
    logger.info("Mission timeout checker started (interval=%ds)", _MISSION_TIMEOUT_INTERVAL)
    while True:
        try:
            await asyncio.sleep(_MISSION_TIMEOUT_INTERVAL)
            from app.worker.cleanup_jobs import run_mission_timeout_check

            await run_mission_timeout_check()
        except asyncio.CancelledError:
            logger.info("Mission timeout checker stopped")
            break
        except Exception as e:
            logger.error("Mission timeout check error: %s", e)


async def daily_maintenance_loop() -> None:
    """Run heavy maintenance tasks once per day (audit log pruning, DB health)."""
    logger.info("Daily maintenance task started (interval=%ds)", _DAILY_MAINTENANCE_INTERVAL)
    while True:
        try:
            await asyncio.sleep(_DAILY_MAINTENANCE_INTERVAL)
            from app.worker.cleanup_jobs import run_daily_maintenance

            await run_daily_maintenance()
        except asyncio.CancelledError:
            logger.info("Daily maintenance task stopped")
            break
        except Exception as e:
            logger.error("Daily maintenance error: %s", e)
