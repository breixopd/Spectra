"""Periodic cleanup tasks for system maintenance."""

from __future__ import annotations

import logging
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete

from app.core.paths import data_path
from app.models.infrastructure import CacheEntry, JobQueue, SystemCache

logger = logging.getLogger(__name__)


async def cleanup_expired_cache(session) -> int:
    """Remove expired system cache entries."""
    now = datetime.now(UTC)
    result = await session.execute(
        delete(SystemCache).where(
            SystemCache.expires_at.isnot(None),
            SystemCache.expires_at < now,
        )
    )
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
    result = await session.execute(
        delete(CacheEntry).where(
            CacheEntry.expires_at.isnot(None),
            CacheEntry.expires_at < cutoff,
        )
    )
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


async def cleanup_transient_mission_artifacts(max_age_hours: int = 6) -> int:
    """Delete stale transient scan workspaces when storage of record is S3."""
    from app.services.storage import get_storage_service

    storage = get_storage_service()
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


async def run_all_cleanup() -> dict[str, int]:
    """Run all cleanup tasks. Intended for periodic scheduling."""
    from app.core.database import async_session_maker
    from app.services.tools.sandbox import get_sandbox_pool

    results: dict[str, int] = {}

    async with async_session_maker() as session:
        results["expired_cache"] = await cleanup_expired_cache(session)
        results["old_cache_entries"] = await cleanup_old_cache_entries(session)
        results["completed_jobs"] = await cleanup_completed_jobs(session)

    sandbox_pool = get_sandbox_pool()
    results["orphaned_sandboxes"] = await cleanup_orphaned_sandboxes(sandbox_pool)
    results["transient_mission_artifacts"] = await cleanup_transient_mission_artifacts()

    total = sum(results.values())
    if total:
        logger.info("Cleanup summary: %s", results)
    return results
