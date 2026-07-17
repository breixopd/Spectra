"""Database maintenance loop (scheduler-owned shell)."""

import logging

import spectra_scheduler.locking as _sched_lock
from spectra_persistence.database import advisory_lock_connection
from spectra_scheduler import async_ops
from spectra_scheduler.locks import _DB_MAINTENANCE_LOCK_ID

logger = logging.getLogger("spectra_scheduler")


class SchedulerDbMaintenanceMixin:
    # Supplied by SchedulerService.
    running: bool

    async def _db_maintenance(self):
        """Weekly VACUUM ANALYZE on high-traffic tables."""
        from spectra_common.config import get_settings

        while self.running:
            settings = get_settings()
            await async_ops.sleep(settings.DB_MAINTENANCE_INTERVAL)
            if not self.running:
                break
            try:
                async with _sched_lock.advisory_lock_owner(
                    _DB_MAINTENANCE_LOCK_ID,
                    connection_factory=advisory_lock_connection,
                ) as lock_owner:
                    if lock_owner is None:
                        logger.debug("DB maintenance lock not acquired — skipping")
                        continue

                    from sqlalchemy import text
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
