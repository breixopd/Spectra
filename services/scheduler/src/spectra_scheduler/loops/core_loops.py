"""Core recurring background loops (sandbox, quotas, metrics, backups, scaling, jobs, etc.)."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import spectra_scheduler.locking as _sched_lock
from spectra_common.constants import SECONDS_PER_HOUR
from spectra_persistence.database import advisory_lock_connection, async_session_maker
from spectra_scheduler import async_ops
from spectra_scheduler.locks import (
    _BACKUP_LOCK_ID,
    _CACHE_CLEANUP_LOCK_ID,
    _CAPACITY_MONITOR_LOCK_ID,
    _EXPLOIT_REFRESH_LOCK_ID,
    _HEALTH_REPORTER_LOCK_ID,
    _METRICS_COLLECTOR_LOCK_ID,
    _PERIODIC_CLEANUP_LOCK_ID,
    _QUOTA_LOCK_ID,
    _SANDBOX_WATCHDOG_LOCK_ID,
    _STALE_JOB_LOCK_ID,
)

logger = logging.getLogger("spectra_scheduler")


class SchedulerCoreLoopsMixin:
    # Supplied by SchedulerService.  Declaring the composed-service contract
    # here keeps each independently testable mixin type-safe.
    running: bool

    async def _sandbox_watchdog(self):
        """Check for stale sandbox containers and clean them up. Runs every 60s."""
        while self.running:
            try:
                async with _sched_lock.advisory_lock_owner(
                    _SANDBOX_WATCHDOG_LOCK_ID,
                    connection_factory=advisory_lock_connection,
                ) as lock_owner:
                    if lock_owner is None:
                        await async_ops.sleep(60)
                        continue

                    from spectra_infra.background_tasks import sandbox_watchdog_loop

                    await sandbox_watchdog_loop()
            except Exception:
                logger.exception("Sandbox watchdog error")
            await async_ops.sleep(60)

    async def _quota_reset(self):
        """Reset daily API usage counters. Runs checking every hour, resets at midnight UTC."""
        while self.running:
            now = datetime.now(UTC)
            tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            sleep_seconds = (tomorrow - now).total_seconds()
            await async_ops.sleep(min(sleep_seconds, SECONDS_PER_HOUR))

            if not self.running:
                break

            try:
                async with _sched_lock.advisory_lock_owner(
                    _QUOTA_LOCK_ID, connection_factory=advisory_lock_connection
                ) as lock_owner:
                    if lock_owner is None:
                        logger.debug("Quota reset lock not acquired — skipping this iteration")
                        continue

                    from spectra_billing.usage_tracker import UsageTracker

                    tracker = UsageTracker()
                    await tracker.reset_daily_counters()
                    logger.info("Daily quota counters reset")
            except Exception:
                logger.exception("Quota reset error")

    async def _metrics_collector(self):
        """Collect and aggregate metrics. Runs every 30s."""
        while self.running:
            try:
                async with _sched_lock.advisory_lock_owner(
                    _METRICS_COLLECTOR_LOCK_ID,
                    connection_factory=advisory_lock_connection,
                ) as lock_owner:
                    if lock_owner is None:
                        await async_ops.sleep(30)
                        continue

                    from spectra_infra.metrics_store import get_metrics_store

                    store = get_metrics_store()
                    if store:
                        await store.collect()
            except Exception:
                logger.exception("Metrics collection error")
            await async_ops.sleep(30)

    async def _health_reporter(self):
        """Report own health status periodically. Runs every 15s."""
        while self.running:
            try:
                async with _sched_lock.advisory_lock_owner(
                    _HEALTH_REPORTER_LOCK_ID,
                    connection_factory=advisory_lock_connection,
                ) as lock_owner:
                    if lock_owner is None:
                        await async_ops.sleep(15)
                        continue

                    from spectra_infra.cache import get_cache

                    cache = get_cache()
                    if cache:
                        await cache.set(
                            "spectra:service:scheduler:heartbeat",
                            {"status": "running", "timestamp": datetime.now(UTC).isoformat()},
                            ttl=60,
                        )
            except Exception:
                logger.exception("Health reporter cache write failed")
            await async_ops.sleep(15)

    async def _backup_scheduler(self):
        """Run automated backups on the configured schedule."""
        from spectra_common.config import get_settings

        while self.running:
            settings = get_settings()
            if not settings.BACKUP_ENABLED:
                await async_ops.sleep(SECONDS_PER_HOUR)  # Check every hour if enabled
                continue

            try:
                async with _sched_lock.advisory_lock_owner(
                    _BACKUP_LOCK_ID, connection_factory=advisory_lock_connection
                ) as lock_owner:
                    if lock_owner is None:
                        logger.debug("Backup scheduler lock not acquired — skipping this iteration")
                        await async_ops.sleep(settings.BACKUP_SCHEDULE_HOURS * SECONDS_PER_HOUR)
                        continue

                    # Skip if a backup ran recently enough on another replica
                    from spectra_infra.cache import get_cache

                    cache = get_cache()
                    if cache:
                        last_ts = await cache.get("last_backup_timestamp")
                        if last_ts is not None:
                            try:
                                last_dt = datetime.fromisoformat(str(last_ts))
                                elapsed = (datetime.now(UTC) - last_dt).total_seconds()
                                if elapsed < settings.BACKUP_SCHEDULE_HOURS * SECONDS_PER_HOUR:
                                    logger.debug("Backup skipped — ran %.0f s ago", elapsed)
                                    await async_ops.sleep(settings.BACKUP_SCHEDULE_HOURS * SECONDS_PER_HOUR)
                                    continue
                            except (ValueError, TypeError) as e:
                                logger.debug("Could not parse last_backup_timestamp: %s", e)

                    from spectra_scaling.infrastructure_services.backup import BackupService

                    svc = BackupService()
                    result = await svc.create_backup()
                    logger.info("Scheduled backup: %s", result.get("status"))

                    if result.get("status") == "success" and cache:
                        await cache.set(
                            "last_backup_timestamp",
                            datetime.now(UTC).isoformat(),
                            ttl=int(settings.BACKUP_SCHEDULE_HOURS * SECONDS_PER_HOUR * 2),
                        )
            except Exception:
                logger.exception("Scheduled backup failed")

            await async_ops.sleep(settings.BACKUP_SCHEDULE_HOURS * SECONDS_PER_HOUR)

    async def _cache_cleanup(self):
        """Delegate to the shared cache_cleanup_loop with automatic restart on failure."""
        while self.running:
            try:
                async with _sched_lock.advisory_lock_owner(
                    _CACHE_CLEANUP_LOCK_ID,
                    connection_factory=advisory_lock_connection,
                ) as lock_owner:
                    if lock_owner is None:
                        await async_ops.sleep(60)
                        continue

                    from spectra_infra.background_tasks import cache_cleanup_loop

                    await cache_cleanup_loop()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Cache cleanup crashed, restarting in 60s")
                await async_ops.sleep(60)

    async def _periodic_cleanup(self):
        """Delegate to the shared periodic_cleanup_loop with automatic restart on failure."""
        while self.running:
            try:
                async with _sched_lock.advisory_lock_owner(
                    _PERIODIC_CLEANUP_LOCK_ID,
                    connection_factory=advisory_lock_connection,
                ) as lock_owner:
                    if lock_owner is None:
                        await async_ops.sleep(60)
                        continue

                    from spectra_infra.background_tasks import periodic_cleanup_loop

                    await periodic_cleanup_loop()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Periodic cleanup crashed, restarting in 60s")
                await async_ops.sleep(60)

    async def _capacity_monitor(self):
        """Monitor network capacity and auto-scale services when enabled."""
        while self.running:
            await async_ops.sleep(60)
            if not self.running:
                break
            try:
                async with _sched_lock.advisory_lock_owner(
                    _CAPACITY_MONITOR_LOCK_ID,
                    connection_factory=advisory_lock_connection,
                ) as lock_owner:
                    if lock_owner is None:
                        continue

                    from spectra_common.config import get_settings

                    settings = get_settings()

                    # Re-create AutoScaler each cycle to pick up runtime setting changes
                    scaler = None
                    if settings.AUTOSCALE_ENABLED:
                        from spectra_scaling.auto_scaler import AutoScaler
                        from spectra_scaling.backends import DockerSwarmBackend
                        from spectra_scaling.config import AutoScalerConfig
                        from spectra_scaling.notifiers import SpectraNotifier

                        config = AutoScalerConfig.from_settings(settings)
                        scaler = AutoScaler(config, DockerSwarmBackend(), SpectraNotifier())

                    # --- Auto-scaling with real metrics ---
                    if scaler is not None:
                        from spectra_scaling.metrics_collector import MetricsCollector

                        collector = MetricsCollector()
                        cluster_metrics = await collector.collect_all()
                        decisions = await scaler.evaluate_and_execute(cluster_metrics)
                        for decision in decisions:
                            if decision.action != "none":
                                await self._send_capacity_alert(
                                    {
                                        "event": f"auto_scaled_{decision.action}",
                                        "service": decision.service,
                                        "replicas": f"{decision.current_replicas} → {decision.desired_replicas}",
                                        "reason": decision.reason,
                                        "utilization_pct": 0,
                                        "total_used": 0,
                                        "total_capacity": 0,
                                    }
                                )

                    # --- Capacity warnings (always active) ---
                    from spectra_persistence.models.server_node import ServerNode

                    async with async_session_maker() as session:
                        from sqlalchemy import select as sa_select

                        result = await session.execute(sa_select(ServerNode).where(ServerNode.is_active))
                        nodes = list(result.scalars().all())

                    if not nodes:
                        continue

                    from spectra_scaling.resource_manager import ResourceManager

                    status = await ResourceManager.check_network_capacity(nodes)

                    if status["at_capacity"]:
                        logger.critical(
                            "CAPACITY ALERT: Network at full capacity (%d/%d containers, %.1f%%)",
                            status["total_used"],
                            status["total_capacity"],
                            status["utilization_pct"],
                        )
                        from spectra_scaling.infrastructure_services.storage_monitor import StorageMonitor

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
                logger.warning("Capacity monitor failed: %s", e)

    async def _send_capacity_alert(self, status: dict) -> None:
        """Send capacity alert via configured notification channels."""
        try:
            from spectra_system.notifications import send_notification

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

    async def _stale_job_recovery(self):
        """Recover jobs stuck in 'in_progress' state. Runs every 5 minutes."""
        from spectra_common.config import get_settings

        while self.running:
            settings = get_settings()
            await async_ops.sleep(settings.STALE_JOB_RECOVERY_INTERVAL)
            if not self.running:
                break
            try:
                async with _sched_lock.advisory_lock_owner(
                    _STALE_JOB_LOCK_ID, connection_factory=advisory_lock_connection
                ) as lock_owner:
                    if lock_owner is None:
                        continue

                    from spectra_infra.queue import PostgresJobQueue

                    mgr = PostgresJobQueue()
                    recovered = await mgr.recover_stale_jobs(max_age_minutes=30)
                    if recovered:
                        logger.info("Recovered %d stale job(s)", recovered)

                    # Check for dead-letter jobs and alert
                    dlq_jobs = await mgr.list_dead_letter_jobs(limit=1)
                    if dlq_jobs:
                        dlq_count = len(await mgr.list_dead_letter_jobs(limit=100))
                        logger.warning("Dead-letter queue has %d jobs", dlq_count)
                        await self._send_capacity_alert(
                            {
                                "event": "dead_letter_alert",
                                "message": f"{dlq_count} jobs in dead-letter queue",
                                "utilization_pct": 0,
                                "total_used": dlq_count,
                                "total_capacity": 0,
                            }
                        )
            except Exception as e:
                logger.warning("Stale job recovery failed: %s", e)

    async def _exploit_db_refresh(self):
        """Periodically refresh exploit database indexes."""
        from spectra_common.config import get_settings

        while self.running:
            settings = get_settings()
            await async_ops.sleep(settings.EXPLOIT_DB_REFRESH_HOURS * SECONDS_PER_HOUR)
            if not self.running:
                break
            try:
                async with _sched_lock.advisory_lock_owner(
                    _EXPLOIT_REFRESH_LOCK_ID,
                    connection_factory=advisory_lock_connection,
                ) as lock_owner:
                    if lock_owner is None:
                        logger.debug("Exploit DB refresh lock not acquired — skipping")
                        continue

                    from spectra_ai_core.exploit_db import get_exploit_db

                    db = get_exploit_db()
                    stats = await db.update()
                    logger.info("Exploit DB refreshed: %s", stats)
            except Exception as e:
                logger.warning("Exploit DB refresh failed: %s", e)
