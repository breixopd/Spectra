"""Spectra Scheduler Service — background maintenance loops.

Runs as a FastAPI microservice with a /health endpoint. Handles:
- Sandbox watchdog (cleanup stale containers)
- Warm pool maintenance
- Quota reset (daily counters)
- Metrics aggregation
"""

import asyncio
import logging
import signal
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from sqlalchemy import text

from app.core.database import async_session_maker

logger = logging.getLogger(__name__)

# Stable advisory lock IDs for inter-replica coordination (PostgreSQL pg_advisory_lock)
_BACKUP_LOCK_ID: int = hash("spectra_backup") & 0x7FFFFFFF
_QUOTA_LOCK_ID: int = hash("spectra_quota_reset") & 0x7FFFFFFF


async def _try_advisory_lock(session, lock_id: int) -> bool:
    """Attempt a non-blocking PostgreSQL advisory lock. Returns True if acquired."""
    result = await session.execute(text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": lock_id})
    return bool(result.scalar())


class SchedulerService:
    """Manages periodic background tasks."""

    def __init__(self):
        self.running = False
        self.tasks: list[asyncio.Task] = []
        self._named_tasks: dict[str, asyncio.Task] = {}

    async def start(self):
        self.running = True
        logger.info("Scheduler service starting...")

        # Start scheduled loops
        self._named_tasks = {
            "sandbox_watchdog": asyncio.create_task(self._sandbox_watchdog()),
            "quota_reset": asyncio.create_task(self._quota_reset()),
            "metrics_collector": asyncio.create_task(self._metrics_collector()),
            "health_reporter": asyncio.create_task(self._health_reporter()),
            "backup_scheduler": asyncio.create_task(self._backup_scheduler()),
            "cache_cleanup": asyncio.create_task(self._cache_cleanup()),
            "periodic_cleanup": asyncio.create_task(self._periodic_cleanup()),
        }
        self.tasks = list(self._named_tasks.values())

        logger.info("Scheduler running with %d tasks", len(self.tasks))
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def stop(self):
        self.running = False
        for task in self.tasks:
            task.cancel()
        logger.info("Scheduler stopped")

    def health(self) -> dict:
        task_status = {name: (not task.done()) for name, task in self._named_tasks.items()}
        alive = any(task_status.values()) if task_status else self.running
        return {
            "status": "healthy" if alive else "degraded",
            "tasks": task_status,
            "running": self.running,
        }

    async def _sandbox_watchdog(self):
        """Check for stale sandbox containers and clean them up. Runs every 60s."""
        while self.running:
            try:
                from app.core.background_tasks import sandbox_watchdog_loop

                await sandbox_watchdog_loop()
            except (OSError, RuntimeError, ValueError) as e:
                logger.error("Sandbox watchdog error: %s", e)
            await asyncio.sleep(60)

    async def _quota_reset(self):
        """Reset daily API usage counters. Runs checking every hour, resets at midnight UTC."""
        while self.running:
            now = datetime.now(UTC)
            tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            sleep_seconds = (tomorrow - now).total_seconds()
            await asyncio.sleep(min(sleep_seconds, 3600))

            if not self.running:
                break

            try:
                async with async_session_maker() as session:
                    if not await _try_advisory_lock(session, _QUOTA_LOCK_ID):
                        logger.debug("Quota reset lock not acquired — skipping this iteration")
                        continue

                from app.services.billing.usage_tracker import UsageTracker

                tracker = UsageTracker()
                await tracker.reset_daily_counters()
                logger.info("Daily quota counters reset")
            except (OSError, RuntimeError, ValueError) as e:
                logger.error("Quota reset error: %s", e)

    async def _metrics_collector(self):
        """Collect and aggregate metrics. Runs every 30s."""
        while self.running:
            try:
                from app.core.metrics_store import get_metrics_store

                store = get_metrics_store()
                if store:
                    await store.collect()
            except (OSError, RuntimeError, ValueError) as e:
                logger.error("Metrics collection error: %s", e)
            await asyncio.sleep(30)

    async def _health_reporter(self):
        """Report own health status periodically. Runs every 15s."""
        while self.running:
            try:
                from app.core.cache import get_cache

                cache = get_cache()
                if cache:
                    await cache.set(
                        "spectra:service:scheduler:heartbeat",
                        {"status": "running", "timestamp": datetime.utcnow().isoformat()},
                        ttl=60,
                    )
            except OSError:
                pass
            await asyncio.sleep(15)

    async def _backup_scheduler(self):
        """Run automated backups on the configured schedule."""
        from app.core.config import get_settings

        while self.running:
            settings = get_settings()
            if not settings.BACKUP_ENABLED:
                await asyncio.sleep(3600)  # Check every hour if enabled
                continue

            try:
                async with async_session_maker() as session:
                    if not await _try_advisory_lock(session, _BACKUP_LOCK_ID):
                        logger.debug("Backup scheduler lock not acquired — skipping this iteration")
                        await asyncio.sleep(settings.BACKUP_SCHEDULE_HOURS * 3600)
                        continue

                    # Skip if a backup ran recently enough on another replica
                    from app.core.cache import get_cache

                    cache = get_cache()
                    if cache:
                        last_ts = await cache.get("last_backup_timestamp")
                        if last_ts is not None:
                            try:
                                last_dt = datetime.fromisoformat(str(last_ts))
                                elapsed = (datetime.now(UTC) - last_dt).total_seconds()
                                if elapsed < settings.BACKUP_SCHEDULE_HOURS * 3600:
                                    logger.debug("Backup skipped — ran %.0f s ago", elapsed)
                                    await asyncio.sleep(settings.BACKUP_SCHEDULE_HOURS * 3600)
                                    continue
                            except (ValueError, TypeError):
                                pass

                from app.services.infrastructure.backup import BackupService

                svc = BackupService()
                result = await svc.create_backup()
                logger.info("Scheduled backup: %s", result.get("status"))

                from app.core.cache import get_cache as _get_cache

                _cache = _get_cache()
                if _cache:
                    await _cache.set(
                        "last_backup_timestamp",
                        datetime.now(UTC).isoformat(),
                        ttl=int(settings.BACKUP_SCHEDULE_HOURS * 3600 * 2),
                    )
            except (OSError, RuntimeError, ValueError) as e:
                logger.error("Scheduled backup failed: %s", e)

            await asyncio.sleep(settings.BACKUP_SCHEDULE_HOURS * 3600)

    async def _cache_cleanup(self):
        """Delegate to the shared cache_cleanup_loop from background_tasks."""
        try:
            from app.core.background_tasks import cache_cleanup_loop

            await cache_cleanup_loop()
        except (OSError, RuntimeError, ValueError) as e:
            logger.error("Cache cleanup error: %s", e)

    async def _periodic_cleanup(self):
        """Delegate to the shared periodic_cleanup_loop from background_tasks."""
        try:
            from app.core.background_tasks import periodic_cleanup_loop

            await periodic_cleanup_loop()
        except (OSError, RuntimeError, ValueError) as e:
            logger.error("Periodic cleanup error: %s", e)


async def main():
    scheduler = SchedulerService()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(scheduler.stop()))

    await scheduler.start()


# --- FastAPI wrapper for health checks and service auth ---

_scheduler_instance: SchedulerService | None = None


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    global _scheduler_instance
    _scheduler_instance = SchedulerService()
    task = asyncio.create_task(_scheduler_instance.start())
    yield
    await _scheduler_instance.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Spectra Scheduler", version="1.0.0", lifespan=lifespan)

from app.core.config import get_settings
from app.core.service_auth import ServiceAuthMiddleware

_settings = get_settings()
_secret = _settings.SERVICE_AUTH_SECRET.get_secret_value()
if _secret:
    app.add_middleware(ServiceAuthMiddleware, secret=_secret)


@app.get("/health")
async def health():
    if _scheduler_instance is None:
        return {"status": "starting", "service": "scheduler"}
    result = _scheduler_instance.health()
    result["service"] = "scheduler"
    return result


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    asyncio.run(main())
