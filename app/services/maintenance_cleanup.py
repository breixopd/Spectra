"""Periodic cleanup task implementations shared by scheduler and workers."""

from __future__ import annotations

import logging
import shutil
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.core.config import get_settings as _get_settings
from app.core.paths import data_path
from app.models.audit_log import AuditLog
from app.models.infrastructure import CacheEntry, JobQueue, SystemCache

logger = logging.getLogger(__name__)


async def cleanup_expired_cache(session) -> int:
    """Remove expired system cache entries."""
    now = datetime.now(UTC)
    result = await session.execute(delete(SystemCache).where(SystemCache.expires_at.isnot(None), SystemCache.expires_at < now))
    await session.commit()
    count = result.rowcount  # type: ignore[union-attr]
    if count:
        logger.info("Cleaned up %d expired system cache entries", count)
    return count


async def cleanup_orphaned_sandboxes(sandbox_pool) -> int:
    """Find and remove sandbox containers that escaped normal cleanup."""
    if not sandbox_pool or not sandbox_pool.available:
        return 0

    cleaned = await sandbox_pool.cleanup_all()
    if cleaned:
        logger.info("Cleaned up %d orphaned sandboxes", cleaned)
    return cleaned


async def cleanup_old_cache_entries(session, max_age_days: int = 7) -> int:
    """Purge cache entries older than max_age_days."""
    cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
    result = await session.execute(delete(CacheEntry).where(CacheEntry.expires_at.isnot(None), CacheEntry.expires_at < cutoff))
    await session.commit()
    count = result.rowcount  # type: ignore[union-attr]
    if count:
        logger.info("Purged %d old cache entries", count)
    return count


async def cleanup_completed_jobs(session, max_age_days: int = 30) -> int:
    """Delete completed/dead-letter jobs older than max_age_days."""
    cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
    result = await session.execute(
        delete(JobQueue).where(
            JobQueue.status.in_(["completed", "dead_letter"]),
            JobQueue.completed_at.isnot(None),
            JobQueue.completed_at < cutoff,
        )
    )
    await session.commit()
    count = result.rowcount  # type: ignore[union-attr]
    if count:
        logger.info("Cleaned up %d old completed/dead-letter jobs", count)
    return count


async def cleanup_audit_logs(session, max_age_days: int | None = None) -> int:
    """Delete audit log entries older than max_age_days."""
    if max_age_days is None:
        from app.core.config import get_settings

        max_age_days = get_settings().AUDIT_LOG_RETENTION_DAYS

    if max_age_days == 0:
        return 0

    cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
    result = await session.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
    await session.commit()
    count = result.rowcount  # type: ignore[union-attr]
    if count:
        logger.info("Cleaned up %d audit log entries older than %d days", count, max_age_days)
    return count


async def cleanup_transient_mission_artifacts(max_age_hours: int = 6) -> int:
    """Delete stale transient scan workspaces when storage of record is S3."""
    try:
        from app.services.storage import get_storage_service

        storage = get_storage_service()
    except (ImportError, ModuleNotFoundError, RuntimeError) as exc:
        logger.warning("Skipping transient mission cleanup; storage client is unavailable: %s", exc)
        return 0

    if not storage.is_s3:
        return 0

    missions_root = data_path("missions")
    if not missions_root.exists():
        return 0

    cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
    removed = 0

    for mission_dir in missions_root.iterdir():
        scans_dir = mission_dir / "scans"
        if not scans_dir.exists():
            continue
        modified = datetime.fromtimestamp(scans_dir.stat().st_mtime, tz=UTC)
        if modified >= cutoff:
            continue
        shutil.rmtree(scans_dir, ignore_errors=True)
        removed += 1
        if mission_dir.exists() and not any(mission_dir.iterdir()):
            shutil.rmtree(mission_dir, ignore_errors=True)

    if removed:
        logger.info("Cleaned up %d stale transient mission workspace(s)", removed)
    return removed


async def cleanup_old_missions(session=None) -> int:
    """Delete completed/failed missions older than MISSION_RETENTION_DAYS."""
    settings = _get_settings()
    retention_days = settings.MISSION_RETENTION_DAYS
    if retention_days <= 0:
        return 0

    close_session = False
    if session is None:
        from app.core.database import async_session_maker

        session = async_session_maker()
        close_session = True

    try:
        from app.models.mission import Mission

        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        result = await session.execute(
            select(Mission.id).where(
                Mission.status.in_(["completed", "failed", "cancelled"]),
                Mission.created_at < cutoff,
            )
        )
        mission_ids = [row[0] for row in result.all()]

        if not mission_ids:
            return 0

        try:
            from app.services.storage import get_storage_service

            storage = get_storage_service()
            for mid in mission_ids:
                keys = await storage.list_objects(settings.S3_BUCKET_MISSIONS, prefix=str(mid))
                for key in keys:
                    await storage.delete(settings.S3_BUCKET_MISSIONS, key)
        except Exception:
            logger.warning("Failed to cleanup S3 artifacts for expired missions", exc_info=True)

        await session.execute(delete(Mission).where(Mission.id.in_(mission_ids)))
        await session.commit()

        logger.info("Cleaned up %d expired missions (retention: %d days)", len(mission_ids), retention_days)
        return len(mission_ids)
    except Exception:
        logger.error("Mission retention cleanup failed", exc_info=True)
        if close_session:
            await session.rollback()
        return 0
    finally:
        if close_session:
            await session.close()
