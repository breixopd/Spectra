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
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from sqlalchemy import text

from app.core.constants import SECONDS_PER_HOUR
from app.core.database import async_session_maker
from app.core.tasks import create_safe_task

logger = logging.getLogger(__name__)

# Stable advisory lock IDs for inter-replica coordination (PostgreSQL pg_advisory_lock)
_BACKUP_LOCK_ID: int = hash("spectra_backup") & 0x7FFFFFFF
_QUOTA_LOCK_ID: int = hash("spectra_quota_reset") & 0x7FFFFFFF
_DB_MAINTENANCE_LOCK_ID: int = hash("spectra_db_maint") & 0x7FFFFFFF
_EXPLOIT_REFRESH_LOCK_ID: int = hash("spectra_exploit_refresh") & 0x7FFFFFFF
_STALE_JOB_LOCK_ID: int = hash("spectra_stale_jobs") & 0x7FFFFFFF
_DOCKER_CLEANUP_LOCK_ID: int = hash("spectra_docker_cleanup") & 0x7FFFFFFF
_SCHEDULER_LEADER_LOCK_ID: int = 8675309  # Global leader election for the scheduler


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
            "sandbox_watchdog": create_safe_task(self._sandbox_watchdog(), name="sandbox_watchdog"),
            "quota_reset": create_safe_task(self._quota_reset(), name="quota_reset"),
            "metrics_collector": create_safe_task(self._metrics_collector(), name="metrics_collector"),
            "health_reporter": create_safe_task(self._health_reporter(), name="health_reporter"),
            "backup_scheduler": create_safe_task(self._backup_scheduler(), name="backup_scheduler"),
            "cache_cleanup": create_safe_task(self._cache_cleanup(), name="cache_cleanup"),
            "periodic_cleanup": create_safe_task(self._periodic_cleanup(), name="periodic_cleanup"),
            "db_maintenance": create_safe_task(self._db_maintenance(), name="db_maintenance"),
            "stale_job_recovery": create_safe_task(self._stale_job_recovery(), name="stale_job_recovery"),
            "exploit_db_refresh": create_safe_task(self._exploit_db_refresh(), name="exploit_db_refresh"),
            "capacity_monitor": create_safe_task(self._capacity_monitor(), name="capacity_monitor"),
            "docker_cleanup": create_safe_task(self._docker_cleanup(), name="docker_cleanup"),
            "disk_monitor": create_safe_task(self._disk_monitor(), name="disk_monitor"),
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
            except Exception:
                logger.exception("Sandbox watchdog error")
            await asyncio.sleep(60)

    async def _quota_reset(self):
        """Reset daily API usage counters. Runs checking every hour, resets at midnight UTC."""
        while self.running:
            now = datetime.now(UTC)
            tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            sleep_seconds = (tomorrow - now).total_seconds()
            await asyncio.sleep(min(sleep_seconds, SECONDS_PER_HOUR))

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
            except Exception:
                logger.exception("Quota reset error")

    async def _metrics_collector(self):
        """Collect and aggregate metrics. Runs every 30s."""
        while self.running:
            try:
                from app.core.metrics_store import get_metrics_store

                store = get_metrics_store()
                if store:
                    await store.collect()
            except Exception:
                logger.exception("Metrics collection error")
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
                        {"status": "running", "timestamp": datetime.now(UTC).isoformat()},
                        ttl=60,
                    )
            except Exception:
                logger.exception("Health reporter cache write failed")
            await asyncio.sleep(15)

    async def _backup_scheduler(self):
        """Run automated backups on the configured schedule."""
        from app.core.config import get_settings

        while self.running:
            settings = get_settings()
            if not settings.BACKUP_ENABLED:
                await asyncio.sleep(SECONDS_PER_HOUR)  # Check every hour if enabled
                continue

            try:
                async with async_session_maker() as session:
                    if not await _try_advisory_lock(session, _BACKUP_LOCK_ID):
                        logger.debug("Backup scheduler lock not acquired — skipping this iteration")
                        await asyncio.sleep(settings.BACKUP_SCHEDULE_HOURS * SECONDS_PER_HOUR)
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
                                if elapsed < settings.BACKUP_SCHEDULE_HOURS * SECONDS_PER_HOUR:
                                    logger.debug("Backup skipped — ran %.0f s ago", elapsed)
                                    await asyncio.sleep(settings.BACKUP_SCHEDULE_HOURS * SECONDS_PER_HOUR)
                                    continue
                            except (ValueError, TypeError) as e:
                                logger.debug("Could not parse last_backup_timestamp: %s", e)

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
                        ttl=int(settings.BACKUP_SCHEDULE_HOURS * SECONDS_PER_HOUR * 2),
                    )
            except Exception:
                logger.exception("Scheduled backup failed")

            await asyncio.sleep(settings.BACKUP_SCHEDULE_HOURS * SECONDS_PER_HOUR)

    async def _cache_cleanup(self):
        """Delegate to the shared cache_cleanup_loop with automatic restart on failure."""
        while self.running:
            try:
                from app.core.background_tasks import cache_cleanup_loop

                await cache_cleanup_loop()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Cache cleanup crashed, restarting in 60s")
                await asyncio.sleep(60)

    async def _periodic_cleanup(self):
        """Delegate to the shared periodic_cleanup_loop with automatic restart on failure."""
        while self.running:
            try:
                from app.core.background_tasks import periodic_cleanup_loop

                await periodic_cleanup_loop()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Periodic cleanup crashed, restarting in 60s")
                await asyncio.sleep(60)

    async def _capacity_monitor(self):
        """Monitor network capacity and auto-scale services when enabled."""
        while self.running:
            await asyncio.sleep(60)
            if not self.running:
                break
            try:
                from app.core.config import get_settings

                settings = get_settings()

                # Re-create AutoScaler each cycle to pick up runtime setting changes
                scaler = None
                if settings.AUTOSCALE_ENABLED:
                    from app.services.scaling.auto_scaler import AutoScaler

                    scaler = AutoScaler(settings)

                # --- Auto-scaling ---
                if scaler is not None:
                    metrics = await self._collect_scaling_metrics()
                    decisions = await scaler.evaluate_and_execute(metrics)
                    for decision in decisions:
                        if decision.action != "none":
                            await self._send_capacity_alert({
                                "event": f"auto_scaled_{decision.action}",
                                "service": decision.service,
                                "replicas": f"{decision.current_replicas} → {decision.desired_replicas}",
                                "reason": decision.reason,
                                "utilization_pct": 0,
                                "total_used": 0,
                                "total_capacity": 0,
                            })

                # --- Capacity warnings (always active) ---
                from app.models.server_node import ServerNode

                async with async_session_maker() as session:
                    from sqlalchemy import select as sa_select

                    result = await session.execute(
                        sa_select(ServerNode).where(ServerNode.is_active)
                    )
                    nodes = result.scalars().all()

                if not nodes:
                    continue

                from app.services.resource_manager import ResourceManager

                status = await ResourceManager.check_network_capacity(nodes)

                if status["at_capacity"]:
                    logger.critical(
                        "CAPACITY ALERT: Network at full capacity (%d/%d containers, %.1f%%)",
                        status["total_used"],
                        status["total_capacity"],
                        status["utilization_pct"],
                    )
                    from app.services.infrastructure.storage_monitor import StorageMonitor

                    if StorageMonitor.should_alert("capacity_at_full"):
                        await self._send_capacity_alert(status)
                elif status["utilization_pct"] > 80:
                    logger.warning(
                        "Capacity warning: %.1f%% utilization (%d/%d)",
                        status["utilization_pct"],
                        status["total_used"],
                        status["total_capacity"],
                    )
            except Exception as e:
                logger.debug("Capacity monitor: %s", e)

    async def _collect_scaling_metrics(self) -> dict:
        """Collect metrics for auto-scaling decisions."""
        import subprocess

        metrics: dict = {}

        # Queue depth from PostgresJobQueue
        try:
            from app.core.queue import queue_metrics

            stats = await queue_metrics()
            metrics["queue_depth"] = stats.get("depth", 0)
            metrics["in_progress"] = stats.get("in_progress", 0)
        except Exception as e:
            logger.warning("Failed to collect queue metrics: %s", e)
            metrics["queue_depth"] = 0
            metrics["in_progress"] = 0

        # Current replica counts from Docker Swarm
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["docker", "service", "ls", "--format", "{{.Name}} {{.Replicas}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    parts = line.split()
                    if len(parts) >= 2:
                        name = parts[0]
                        replicas = parts[1].split("/")
                        count = int(replicas[-1]) if replicas else 1
                        if "worker" in name.lower():
                            metrics["worker_replicas"] = count
                        elif "app" in name.lower():
                            metrics["api_replicas"] = count
                        elif "ai" in name.lower():
                            metrics["ai_replicas"] = count
                        elif "scheduler" in name.lower():
                            metrics["scheduler_replicas"] = count
        except Exception as e:
            logger.warning("Failed to query Docker Swarm replicas: %s", e)

        # Estimate utilization from queue stats
        worker_count = metrics.get("worker_replicas", 1)
        in_progress = metrics.get("in_progress", 0)
        metrics["worker_utilization"] = min(1.0, in_progress / max(1, worker_count))

        return metrics

    async def _send_capacity_alert(self, status: dict) -> None:
        """Send capacity alert via configured notification channels."""
        try:
            from app.services.notifications import send_notification

            await send_notification(
                title="Capacity Alert",
                message=(
                    f"Network at {status['utilization_pct']:.1f}% capacity "
                    f"({status['total_used']}/{status['total_capacity']} containers)"
                ),
                priority="urgent",
                tags=["warning", "capacity"],
            )
        except Exception as e:
            logger.warning("Capacity alert send failed: %s", e)

    async def _db_maintenance(self):
        """Weekly VACUUM ANALYZE on high-traffic tables."""
        from app.core.config import get_settings

        while self.running:
            settings = get_settings()
            await asyncio.sleep(settings.DB_MAINTENANCE_INTERVAL)
            if not self.running:
                break
            try:
                async with async_session_maker() as session:
                    if not await _try_advisory_lock(session, _DB_MAINTENANCE_LOCK_ID):
                        logger.debug("DB maintenance lock not acquired — skipping")
                        continue

                from sqlalchemy.ext.asyncio import create_async_engine

                engine = create_async_engine(
                    settings.DATABASE_URL.get_secret_value(), isolation_level="AUTOCOMMIT"
                )
                VACUUM_TABLES = frozenset({"missions", "findings", "audit_logs", "job_queue", "cache_entries"})
                async with engine.connect() as conn:
                    for table in VACUUM_TABLES:
                        if not table.isidentifier():
                            raise ValueError(f"Invalid table name: {table}")
                        await conn.execute(text(f"VACUUM ANALYZE {table}"))
                await engine.dispose()
                logger.info("DB maintenance completed: VACUUM ANALYZE on key tables")
            except Exception as e:
                logger.warning("DB maintenance failed: %s", e)

    async def _stale_job_recovery(self):
        """Recover jobs stuck in 'in_progress' state. Runs every 5 minutes."""
        from app.core.config import get_settings

        while self.running:
            settings = get_settings()
            await asyncio.sleep(settings.STALE_JOB_RECOVERY_INTERVAL)
            if not self.running:
                break
            try:
                async with async_session_maker() as session:
                    if not await _try_advisory_lock(session, _STALE_JOB_LOCK_ID):
                        continue

                from app.core.queue import PostgresJobQueue

                mgr = PostgresJobQueue()
                recovered = await mgr.recover_stale_jobs(max_age_minutes=30)
                if recovered:
                    logger.info("Recovered %d stale job(s)", recovered)

                # Check for dead-letter jobs and alert
                dlq_jobs = await mgr.list_dead_letter_jobs(limit=1)
                if dlq_jobs:
                    dlq_count = len(await mgr.list_dead_letter_jobs(limit=100))
                    logger.warning("Dead-letter queue has %d jobs", dlq_count)
                    await self._send_capacity_alert({
                        "event": "dead_letter_alert",
                        "message": f"{dlq_count} jobs in dead-letter queue",
                        "utilization_pct": 0,
                        "total_used": dlq_count,
                        "total_capacity": 0,
                    })
            except Exception as e:
                logger.warning("Stale job recovery failed: %s", e)

    async def _exploit_db_refresh(self):
        """Periodically refresh exploit database indexes."""
        from app.core.config import get_settings

        while self.running:
            settings = get_settings()
            await asyncio.sleep(settings.EXPLOIT_DB_REFRESH_HOURS * SECONDS_PER_HOUR)
            if not self.running:
                break
            try:
                async with async_session_maker() as session:
                    if not await _try_advisory_lock(session, _EXPLOIT_REFRESH_LOCK_ID):
                        logger.debug("Exploit DB refresh lock not acquired — skipping")
                        continue

                from app.services.exploit_db import get_exploit_db

                db = get_exploit_db()
                stats = await db.update()
                logger.info("Exploit DB refreshed: %s", stats)
            except Exception as e:
                logger.warning("Exploit DB refresh failed: %s", e)


    async def _docker_cleanup(self):
        """Weekly Docker resource cleanup — prune dangling images and exited containers."""
        from app.core.config import get_settings

        while self.running:
            settings = get_settings()
            await asyncio.sleep(settings.DOCKER_CLEANUP_INTERVAL)
            if not self.running:
                break
            try:
                async with async_session_maker() as session:
                    if not await _try_advisory_lock(session, _DOCKER_CLEANUP_LOCK_ID):
                        logger.debug("Docker cleanup lock not acquired — skipping")
                        continue

                import subprocess

                # Prune exited containers
                await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "container", "prune", "-f", "--filter", "until=48h"],
                    capture_output=True, text=True, timeout=60,
                )
                # Prune dangling images
                await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "image", "prune", "-f", "--filter", "until=168h"],
                    capture_output=True, text=True, timeout=120,
                )
                # Prune dangling volumes (only truly orphaned)
                await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "volume", "prune", "-f"],
                    capture_output=True, text=True, timeout=60,
                )
                # Prune exited Swarm task containers
                await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "container", "prune", "-f",
                     "--filter", "label=com.docker.swarm.task",
                     "--filter", "status=exited"],
                    capture_output=True, text=True, timeout=60,
                )
                logger.info("Docker cleanup completed: pruned containers, images, volumes, swarm tasks")
            except Exception as e:
                logger.warning("Docker cleanup failed: %s", e)

    async def _disk_monitor(self):
        """Monitor disk space and alert when low (with dedup)."""
        from app.services.infrastructure.storage_monitor import StorageMonitor

        while self.running:
            await asyncio.sleep(300)  # 5 minutes
            if not self.running:
                break
            try:
                import shutil

                usage = shutil.disk_usage("/")
                free_pct = usage.free / usage.total * 100
                if free_pct < 10:
                    logger.critical(
                        "DISK SPACE CRITICAL: %.1f%% free (%d MB remaining)",
                        free_pct,
                        usage.free // (1024 * 1024),
                    )
                    if StorageMonitor.should_alert("disk_space_critical"):
                        await self._send_capacity_alert({
                            "event": "disk_space_critical",
                            "free_pct": round(free_pct, 1),
                            "free_mb": usage.free // (1024 * 1024),
                            "utilization_pct": round(100 - free_pct, 1),
                            "total_used": (usage.total - usage.free) // (1024 * 1024),
                            "total_capacity": usage.total // (1024 * 1024),
                        })
                elif free_pct < 20:
                    logger.warning("Disk space low: %.1f%% free", free_pct)
            except Exception as e:
                logger.debug("Disk monitor: %s", e)


async def main():
    scheduler = SchedulerService()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(scheduler.stop()))

    await scheduler.start()


# --- FastAPI wrapper for health checks and service auth ---

_scheduler_instance: SchedulerService | None = None


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    global _scheduler_instance
    _scheduler_instance = SchedulerService()
    task = create_safe_task(_leader_election_loop(_scheduler_instance), name="leader_election")
    yield
    await _scheduler_instance.stop()
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def _leader_election_loop(scheduler: SchedulerService) -> None:
    """Try to acquire the global scheduler leader lock; stand by if another replica holds it."""
    while True:
        try:
            async with async_session_maker() as session:
                is_leader = await _try_advisory_lock(session, _SCHEDULER_LEADER_LOCK_ID)
                if is_leader:
                    logger.info("Scheduler acquired leader lock — starting tasks")
                    try:
                        await scheduler.start()
                    finally:
                        await session.execute(
                            text("SELECT pg_advisory_unlock(:lock_id)"),
                            {"lock_id": _SCHEDULER_LEADER_LOCK_ID},
                        )
                    return  # start() runs until stopped
            # Not leader — stand by
            logger.info("Another scheduler is leader, standing by...")
            await asyncio.sleep(15)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Leader election error — retrying in 15s")
            await asyncio.sleep(15)


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
