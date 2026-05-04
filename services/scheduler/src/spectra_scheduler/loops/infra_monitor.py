"""Infrastructure and disk monitoring loops (scheduler-owned shell)."""

import logging

import spectra_scheduler.locking as _sched_lock
from spectra_platform.core.database import advisory_lock_connection
from spectra_scheduler import async_ops
from spectra_scheduler.locks import (
    _DISK_MONITOR_LOCK_ID,
    _INFRA_MONITOR_LOCK_ID,
)

logger = logging.getLogger("spectra_scheduler")


class SchedulerInfraMonitorMixin:
    async def _send_infra_alert(self, *, event: str, message: str, priority: str = "urgent") -> None:
        """Send infrastructure monitor alerts through the configured notifier."""
        try:
            from spectra_platform.services.infrastructure.storage_monitor import StorageMonitor
            from spectra_platform.services.notifications import send_notification

            if not StorageMonitor.should_alert(event):
                return
            await send_notification(
                title="Infrastructure Alert",
                message=message,
                priority=priority,
                tags=["warning", "infrastructure", event],
            )
        except Exception as e:
            logger.warning("Infrastructure alert send failed: %s", e)

    async def _check_postgres_pool_pressure(self, settings) -> None:
        from spectra_platform.core.database import engine

        if engine is None:
            return
        pool = engine.sync_engine.pool
        checked_out = getattr(pool, "checkedout", lambda: 0)()
        base_size = getattr(pool, "size", lambda: 0)()
        max_overflow = max(getattr(pool, "_max_overflow", 0), 0)
        capacity = max(base_size + max_overflow, 1)
        utilization_pct = checked_out / capacity * 100
        threshold = settings.INFRA_MONITOR_PG_THRESHOLD
        if utilization_pct >= threshold:
            logger.warning(
                "PostgreSQL pool pressure high: %.1f%% (%d/%d connections)",
                utilization_pct,
                checked_out,
                capacity,
            )
            await self._send_infra_alert(
                event="postgres_pool_pressure",
                message=f"PostgreSQL pool pressure is {utilization_pct:.1f}% ({checked_out}/{capacity} connections)",
            )

    async def _check_redis_memory_pressure(self, settings) -> None:
        redis_url = getattr(settings, "REDIS_URL", "") or settings.RATE_LIMIT_STORAGE
        if not redis_url or not redis_url.startswith(("redis://", "rediss://")):
            return

        import redis.asyncio as aioredis

        client = aioredis.from_url(redis_url, socket_timeout=2)
        try:
            info = await client.info("memory")
        finally:
            close = getattr(client, "aclose", None) or getattr(client, "close", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result

        used_memory = int(info.get("used_memory", 0) or 0)
        max_memory = int(info.get("maxmemory", 0) or 0)
        if max_memory <= 0:
            return

        utilization_pct = used_memory / max_memory * 100
        threshold = settings.INFRA_MONITOR_REDIS_THRESHOLD
        if utilization_pct >= threshold:
            logger.warning(
                "Redis memory pressure high: %.1f%% (%d/%d bytes)",
                utilization_pct,
                used_memory,
                max_memory,
            )
            await self._send_infra_alert(
                event="redis_memory_pressure",
                message=f"Redis memory pressure is {utilization_pct:.1f}% ({used_memory}/{max_memory} bytes)",
            )

    async def _infrastructure_monitor(self):
        """Monitor configured infrastructure thresholds. Runs every 5 minutes."""
        from spectra_platform.core.config import get_settings

        while self.running:
            await async_ops.sleep(300)
            if not self.running:
                break
            try:
                async with _sched_lock.advisory_lock_owner(
                    _INFRA_MONITOR_LOCK_ID,
                    connection_factory=advisory_lock_connection,
                ) as lock_owner:
                    if lock_owner is None:
                        continue

                    settings = get_settings()
                    if not settings.INFRA_MONITOR_ENABLED:
                        continue

                    await self._check_postgres_pool_pressure(settings)
                    await self._check_redis_memory_pressure(settings)
            except Exception as e:
                logger.warning("Infrastructure monitor failed: %s", e)

    async def _disk_monitor(self):
        """Monitor disk space and alert when low (with dedup)."""
        from spectra_platform.services.infrastructure.storage_monitor import StorageMonitor

        while self.running:
            await async_ops.sleep(300)  # 5 minutes
            if not self.running:
                break
            try:
                async with _sched_lock.advisory_lock_owner(
                    _DISK_MONITOR_LOCK_ID,
                    connection_factory=advisory_lock_connection,
                ) as lock_owner:
                    if lock_owner is None:
                        continue

                    import shutil

                    from spectra_platform.core.config import get_settings

                    settings = get_settings()
                    if not settings.INFRA_MONITOR_ENABLED:
                        continue

                    usage = shutil.disk_usage("/")
                    free_pct = usage.free / usage.total * 100
                    used_pct = 100 - free_pct
                    critical_threshold = settings.INFRA_MONITOR_STORAGE_THRESHOLD
                    warning_threshold = max(critical_threshold - 10, 0)
                    if used_pct >= critical_threshold:
                        logger.critical(
                            "DISK SPACE CRITICAL: %.1f%% free, %.1f%% used (%d MB remaining)",
                            free_pct,
                            used_pct,
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
                    elif used_pct >= warning_threshold:
                        logger.warning("Disk space low: %.1f%% free, %.1f%% used", free_pct, used_pct)
            except Exception as e:
                logger.warning("Disk monitor failed: %s", e)
