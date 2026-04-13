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

from fastapi import FastAPI, Response, status
from sqlalchemy import text

from app.core.advisory_locks import stable_lock_id
from app.core.constants import SECONDS_PER_HOUR
from app.core.database import async_session_maker
from app.core.tasks import create_safe_task

logger = logging.getLogger(__name__)

# Stable advisory lock IDs for inter-replica coordination (PostgreSQL pg_advisory_lock)
_BACKUP_LOCK_ID: int = stable_lock_id("spectra_backup")
_QUOTA_LOCK_ID: int = stable_lock_id("spectra_quota_reset")
_DB_MAINTENANCE_LOCK_ID: int = stable_lock_id("spectra_db_maint")
_EXPLOIT_REFRESH_LOCK_ID: int = stable_lock_id("spectra_exploit_refresh")
_STALE_JOB_LOCK_ID: int = stable_lock_id("spectra_stale_jobs")
_DOCKER_CLEANUP_LOCK_ID: int = stable_lock_id("spectra_docker_cleanup")
_IMAGE_UPDATE_LOCK_ID: int = stable_lock_id("spectra_image_update")
_SANDBOX_WATCHDOG_LOCK_ID: int = stable_lock_id("spectra_sandbox_watchdog")
_METRICS_COLLECTOR_LOCK_ID: int = stable_lock_id("spectra_metrics_collector")
_HEALTH_REPORTER_LOCK_ID: int = stable_lock_id("spectra_health_reporter")
_CACHE_CLEANUP_LOCK_ID: int = stable_lock_id("spectra_cache_cleanup")
_PERIODIC_CLEANUP_LOCK_ID: int = stable_lock_id("spectra_periodic_cleanup")
_CAPACITY_MONITOR_LOCK_ID: int = stable_lock_id("spectra_capacity_monitor")
_DISK_MONITOR_LOCK_ID: int = stable_lock_id("spectra_disk_monitor")
_SCHEDULER_LEADER_LOCK_ID: int = stable_lock_id("spectra_scheduler_leader")

_SCHEDULER_TASK_SPECS: tuple[tuple[str, str], ...] = (
    ("sandbox_watchdog", "_sandbox_watchdog"),
    ("quota_reset", "_quota_reset"),
    ("metrics_collector", "_metrics_collector"),
    ("health_reporter", "_health_reporter"),
    ("backup_scheduler", "_backup_scheduler"),
    ("cache_cleanup", "_cache_cleanup"),
    ("periodic_cleanup", "_periodic_cleanup"),
    ("db_maintenance", "_db_maintenance"),
    ("stale_job_recovery", "_stale_job_recovery"),
    ("exploit_db_refresh", "_exploit_db_refresh"),
    ("capacity_monitor", "_capacity_monitor"),
    ("docker_cleanup", "_docker_cleanup"),
    ("disk_monitor", "_disk_monitor"),
    ("image_update_check", "_image_update_check"),
)


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
            task_name: create_safe_task(getattr(self, method_name)(), name=task_name)
            for task_name, method_name in _SCHEDULER_TASK_SPECS
        }
        self.tasks = list(self._named_tasks.values())

        logger.info("Scheduler running with %d tasks", len(self.tasks))
        task_names = list(self._named_tasks.keys())
        results = await asyncio.gather(*self.tasks, return_exceptions=True)
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
            status = "standby"
        elif any(state != "alive" for state in task_status.values()):
            status = "degraded"
        else:
            status = "healthy"
        return {
            "status": status,
            "tasks": task_status,
            "running": self.running,
        }

    async def _sandbox_watchdog(self):
        """Check for stale sandbox containers and clean them up. Runs every 60s."""
        while self.running:
            try:
                async with async_session_maker() as session:
                    if not await _try_advisory_lock(session, _SANDBOX_WATCHDOG_LOCK_ID):
                        await asyncio.sleep(60)
                        continue

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
                async with async_session_maker() as session:
                    if not await _try_advisory_lock(session, _METRICS_COLLECTOR_LOCK_ID):
                        await asyncio.sleep(30)
                        continue

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
                async with async_session_maker() as session:
                    if not await _try_advisory_lock(session, _HEALTH_REPORTER_LOCK_ID):
                        await asyncio.sleep(15)
                        continue

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
                async with async_session_maker() as session:
                    if not await _try_advisory_lock(session, _CACHE_CLEANUP_LOCK_ID):
                        await asyncio.sleep(60)
                        continue

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
                async with async_session_maker() as session:
                    if not await _try_advisory_lock(session, _PERIODIC_CLEANUP_LOCK_ID):
                        await asyncio.sleep(60)
                        continue

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
                async with async_session_maker() as session:
                    if not await _try_advisory_lock(session, _CAPACITY_MONITOR_LOCK_ID):
                        continue

                from app.core.config import get_settings

                settings = get_settings()

                # Re-create AutoScaler each cycle to pick up runtime setting changes
                scaler = None
                if settings.AUTOSCALE_ENABLED:
                    from app.services.scaling.auto_scaler import AutoScaler
                    from app.services.scaling.backends import DockerSwarmBackend
                    from app.services.scaling.config import AutoScalerConfig
                    from app.services.scaling.notifiers import SpectraNotifier

                    config = AutoScalerConfig.from_settings(settings)
                    scaler = AutoScaler(config, DockerSwarmBackend(), SpectraNotifier())

                # --- Auto-scaling with real metrics ---
                if scaler is not None:
                    from app.services.scaling.metrics_collector import MetricsCollector

                    collector = MetricsCollector()
                    cluster_metrics = await collector.collect_all()
                    decisions = await scaler.evaluate_and_execute(cluster_metrics)
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
                    settings.DATABASE_URL.get_secret_value(),
                    isolation_level="AUTOCOMMIT",
                    pool_pre_ping=True,
                    pool_recycle=300,
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

                from app.services.scaling.docker_client import (
                    prune_containers,
                    prune_images,
                    prune_volumes,
                )

                # Prune exited containers
                await prune_containers(filters={"until": ["48h"]})
                # Prune dangling images
                await prune_images(filters={"until": ["168h"]})
                # Prune dangling volumes (only truly orphaned)
                await prune_volumes()
                # Prune exited Swarm task containers
                await prune_containers(filters={
                    "label": ["com.docker.swarm.task"],
                    "status": ["exited"],
                })
                logger.info("Docker cleanup completed: pruned containers, images, volumes, swarm tasks")
            except Exception as e:
                logger.warning("Docker cleanup failed: %s", e)

    async def _image_update_check(self):
        """Check for new image versions and trigger rolling updates."""
        from app.core.config import get_settings

        while self.running:
            settings = get_settings()
            await asyncio.sleep(settings.IMAGE_CHECK_INTERVAL)
            if not self.running:
                break
            try:
                async with async_session_maker() as session:
                    if not await _try_advisory_lock(session, _IMAGE_UPDATE_LOCK_ID):
                        logger.debug("Image update lock not acquired — skipping")
                        continue

                from app.services.scaling.image_updater import check_and_update_services

                results = await check_and_update_services(apply=settings.IMAGE_AUTO_UPDATE)
                if results:
                    for r in results:
                        if r.success and not r.error:
                            logger.info("Auto-updated %s: %s → %s", r.service, r.old_digest, r.new_digest)
                            await self._send_update_notification(
                                f"Auto-updated {r.service}",
                                f"Digest: {r.old_digest} → {r.new_digest}",
                                level="info",
                            )
                        elif not r.success:
                            logger.error("Auto-update failed for %s: %s", r.service, r.error)
                            await self._send_update_notification(
                                f"Auto-update failed: {r.service}",
                                r.error,
                                level="error",
                            )
            except Exception:
                logger.exception("Image update check error")

    async def _send_update_notification(self, title: str, message: str, *, level: str = "info") -> None:
        """Send image update notification via configured channels."""
        try:
            from app.services.notifications import send_notification

            await send_notification(
                title=title,
                message=message,
                priority="normal" if level == "info" else "urgent",
                tags=["image-update", level],
            )
        except Exception as e:
            logger.warning("Image update notification failed: %s", e)

    async def _disk_monitor(self):
        """Monitor disk space and alert when low (with dedup)."""
        from app.services.infrastructure.storage_monitor import StorageMonitor

        while self.running:
            await asyncio.sleep(300)  # 5 minutes
            if not self.running:
                break
            try:
                async with async_session_maker() as session:
                    if not await _try_advisory_lock(session, _DISK_MONITOR_LOCK_ID):
                        continue

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

    # Auto-register this machine as a pool node
    try:
        from app.services.scaling.pool_manager import get_pool_manager

        pool = get_pool_manager()
        node = await pool.register_local_node()
        logger.info("Local pool node ready: %s (id=%s)", node.get("name"), node.get("id"))
    except Exception:
        logger.warning("Failed to auto-register local node — continuing", exc_info=True)

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

from app.core.config import settings as _settings
from app.core.service_auth import ServiceAuthMiddleware

_secret = _settings.SERVICE_AUTH_SECRET.get_secret_value()
if _secret:
    app.add_middleware(ServiceAuthMiddleware, secret=_secret)


@app.get("/health")
async def health(response: Response):
    if _scheduler_instance is None:
        return {"status": "starting", "service": "scheduler"}
    result = _scheduler_instance.health()
    result["service"] = "scheduler"
    if result.get("status") == "degraded":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result


@app.get("/internal/metrics")
async def internal_node_metrics():
    """Return local system metrics. Service auth enforced by middleware."""
    from app.services.scaling.node_metrics import collect_node_metrics

    metrics = collect_node_metrics("scheduler")
    return metrics.to_dict()


@app.get("/internal/scaling/dashboard")
async def internal_scaling_dashboard():
    """Comprehensive scaling dashboard data — cluster, services, nodes, autoscaler, alerts."""
    from app.core.config import get_settings as _get_settings
    from app.services.scaling.auto_scaler import AutoScaler, get_scaling_history
    from app.services.scaling.backends import DockerSwarmBackend
    from app.services.scaling.config import AutoScalerConfig
    from app.services.scaling.metrics_collector import MetricsCollector
    from app.services.scaling.notifiers import LogNotifier

    settings = _get_settings()
    collector = MetricsCollector()
    cluster = await collector.collect_all()
    cnm = cluster.cluster_node_metrics

    # --- Cluster summary ---
    cluster_summary = {
        "total_nodes": cnm.total_nodes if cnm else cluster.nodes_total,
        "healthy_nodes": cnm.healthy_nodes if cnm else cluster.nodes_healthy,
        "total_cpu_percent": round(cnm.avg_cpu_percent, 1) if cnm else round(cluster.system.cpu_percent, 1),
        "total_memory_percent": round(cnm.avg_memory_percent, 1) if cnm else round(cluster.system.memory_percent, 1),
        "min_disk_free_gb": round(cnm.min_disk_free_gb, 1) if cnm else round(cluster.system.disk_free_gb, 1),
    }

    # --- Per-service info with node placement ---
    services_info: dict[str, dict] = {}
    for svc_name, svc in cluster.services.items():
        svc_nodes: list[str] = []
        try:
            from app.services.scaling.docker_client import get_service_task_nodes

            svc_nodes = await get_service_task_nodes(svc_name)
        except Exception:
            pass

        # Check update availability from image_updater cache
        update_available = False
        try:
            from app.services.scaling.image_updater import get_update_status
            status = get_update_status()
            for s in status.get("services", []):
                if s.get("service") == svc_name:
                    update_available = s.get("update_available", False)
                    break
        except Exception:
            pass

        services_info[svc_name] = {
            "replicas": svc.replicas,
            "desired": svc.desired_replicas,
            "healthy": svc.running_tasks,
            "cpu_percent": round(svc.cpu_percent, 2),
            "memory_mb": round(svc.memory_mb, 1),
            "update_available": update_available,
            "nodes": svc_nodes,
        }

    # --- Per-node breakdown ---
    nodes_list: list[dict] = []
    if cnm:
        # Gather which services run on which node
        node_services: dict[str, list[str]] = {}
        for svc_name, svc_data in services_info.items():
            for node_name in svc_data.get("nodes", []):
                node_services.setdefault(node_name, []).append(svc_name)

        for n in cnm.per_node:
            nodes_list.append({
                "name": n.name,
                "service_type": n.service_type,
                "cpu_percent": round(n.cpu_percent, 1),
                "memory_percent": round(n.memory_percent, 1),
                "disk_free_gb": round(n.disk_free_gb, 1),
                "services": node_services.get(n.name, []),
                "last_metrics_at": n.last_metrics_at,
            })

    # --- Autoscaler state ---
    scaler_config = AutoScalerConfig.from_settings(settings)
    scaler = AutoScaler(scaler_config, DockerSwarmBackend(), LogNotifier())
    scaler_status = scaler.get_status()
    history = get_scaling_history()

    autoscaler_info = {
        "enabled": settings.AUTOSCALE_ENABLED,
        "policies": scaler_status.get("policies", {}),
        "recent_actions": history[-20:],  # Last 20 for the dashboard
    }

    # --- Alerts ---
    alerts: list[dict] = []
    if cnm:
        for n in cnm.per_node:
            if n.memory_percent > 95:
                alerts.append({"severity": "critical", "message": f"{n.name} memory at {n.memory_percent:.1f}%", "at": n.last_metrics_at})
            elif n.memory_percent > 85:
                alerts.append({"severity": "warning", "message": f"{n.name} memory at {n.memory_percent:.1f}%", "at": n.last_metrics_at})
            if 0 < n.disk_free_gb < 5:
                alerts.append({"severity": "critical", "message": f"{n.name} disk free {n.disk_free_gb:.1f}GB", "at": n.last_metrics_at})
            elif 0 < n.disk_free_gb < 10:
                alerts.append({"severity": "warning", "message": f"{n.name} disk free {n.disk_free_gb:.1f}GB", "at": n.last_metrics_at})
    if cluster.system.cpu_percent > 90:
        alerts.append({"severity": "warning", "message": f"Local CPU at {cluster.system.cpu_percent:.1f}%", "at": cluster.timestamp.isoformat()})

    return {
        "cluster": cluster_summary,
        "services": services_info,
        "nodes": nodes_list,
        "autoscaler": autoscaler_info,
        "alerts": alerts,
    }


@app.get("/internal/updates/status")
async def internal_update_status():
    """Return service image versions and update availability."""
    from app.services.scaling.image_updater import get_update_status

    return get_update_status()


@app.post("/internal/updates/apply")
async def internal_update_apply(request_body: dict):
    """Trigger an image update for a specific service or all managed services."""
    from app.services.scaling.image_updater import MANAGED_SERVICES, check_and_update_services

    target = request_body.get("service")
    if target and target not in MANAGED_SERVICES:
        return {"success": False, "error": f"Unknown service: {target}"}

    # Temporarily override the module-level set if a single service is requested
    original = None
    if target:
        import app.services.scaling.image_updater as _updater
        original = _updater.MANAGED_SERVICES
        _updater.MANAGED_SERVICES = {target}

    try:
        results = await check_and_update_services(apply=True)
    finally:
        if original is not None:
            _updater.MANAGED_SERVICES = original

    return {
        "results": [
            {"service": r.service, "old_digest": r.old_digest, "new_digest": r.new_digest,
             "success": r.success, "error": r.error}
            for r in results
        ],
    }


@app.get("/internal/updates/rollback-candidates")
async def internal_rollback_candidates():
    """Return services that have a previous version available for rollback."""
    from app.services.scaling.image_updater import get_rollback_candidates

    return {"candidates": get_rollback_candidates()}


@app.post("/internal/updates/rollback")
async def internal_rollback(request_body: dict):
    """Rollback a service using Swarm's PreviousSpec."""
    from app.services.scaling.docker_client import rollback_service
    from app.services.scaling.image_updater import MANAGED_SERVICES

    service = request_body.get("service", "")
    if not service:
        return {"success": False, "error": "Missing 'service' field"}
    if service not in MANAGED_SERVICES:
        return {"success": False, "error": f"Unknown service: {service}"}

    success = await rollback_service(service)
    return {"success": success, "service": service}


# --- Internal scaling proxy (runs on Swarm manager node) ---

_INTERNAL_ALLOWED_SERVICES = frozenset({
    "spectra_app",
    "spectra_worker",
    "spectra_ai-svc",
    "spectra_scheduler",
    "spectra_caddy",
})


@app.post("/internal/scaling/action")
async def internal_scaling_action(request_body: dict):
    """Execute a Docker scaling command on behalf of a non-manager app replica."""
    action = request_body.get("action", "")
    service = request_body.get("service", "")

    if action not in ("scale_up", "scale_down", "restart"):
        return {"success": False, "action": action, "service": service, "error": "Invalid action"}
    from app.services.scaling.docker_client import (
        get_service,
        restart_service,
        scale_service,
    )

    if service not in _INTERNAL_ALLOWED_SERVICES:
        return {"success": False, "action": action, "service": service, "error": "Service not allowed"}

    try:
        if action in ("scale_up", "scale_down"):
            svc_info = await get_service(service)
            current = svc_info.desired_replicas if svc_info else 1
            new_count = current + 1 if action == "scale_up" else max(1, current - 1)
            success = await scale_service(service, new_count)

        elif action == "restart":
            success = await restart_service(service)

        else:
            success = False

    except Exception:
        logger.exception("Internal scaling action failed: %s %s", action, service)
        success = False

    return {"success": success, "action": action, "service": service}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    asyncio.run(main())
