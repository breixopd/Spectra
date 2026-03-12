"""Periodic cleanup tasks for system maintenance."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, text, update

from app.models.infrastructure import CacheEntry, JobQueue, SystemCache

logger = logging.getLogger("spectra.worker.cleanup")


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


async def cleanup_expired_sessions(session) -> int:
    """Remove expired user sessions and revoked tokens."""
    from app.models.infrastructure import SystemCache

    now = datetime.now(UTC)
    result = await session.execute(
        delete(SystemCache).where(
            SystemCache.key.like("spectra:session:%"),
            SystemCache.expires_at.isnot(None),
            SystemCache.expires_at < now,
        )
    )
    await session.commit()
    count = result.rowcount  # type: ignore[union-attr]
    if count:
        logger.info("Cleaned up %d expired sessions/tokens", count)
    return count


async def cleanup_old_audit_logs(session, max_age_days: int = 90) -> int:
    """Purge audit log entries older than max_age_days."""
    from app.models.audit_log import AuditLog

    cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
    result = await session.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
    await session.commit()
    count = result.rowcount  # type: ignore[union-attr]
    if count:
        logger.info("Purged %d audit logs older than %d days", count, max_age_days)
    return count


async def check_mission_timeouts(session, max_hours: int = 24) -> int:
    """Mark missions running longer than max_hours as timed out."""
    from app.core.enums import MissionStatus
    from app.core.events import EventType, events
    from app.models.mission import Mission
    from app.services.notifications import send_notification

    cutoff = datetime.now(UTC) - timedelta(hours=max_hours)
    active_statuses = [
        MissionStatus.RUNNING.value,
        MissionStatus.SCANNING.value,
        MissionStatus.ANALYZING.value,
        MissionStatus.EXECUTING.value,
        MissionStatus.EXPLOITING.value,
        MissionStatus.PLANNING.value,
        MissionStatus.SCOPING.value,
        MissionStatus.INITIALIZING.value,
    ]

    result = await session.execute(
        select(Mission).where(
            Mission.status.in_(active_statuses),
            Mission.updated_at < cutoff,
        )
    )
    missions = list(result.scalars().all())
    if not missions:
        return 0

    timed_out_ids = [m.id for m in missions]
    await session.execute(
        update(Mission).where(Mission.id.in_(timed_out_ids)).values(status=MissionStatus.TIMED_OUT.value)
    )
    await session.commit()

    for mission in missions:
        logger.warning(
            "Mission %s timed out after %d hours (target=%s)",
            mission.id,
            max_hours,
            mission.target,
        )
        try:
            await events.emit(
                EventType.MISSION_TIMED_OUT,
                source="maintenance",
                mission_id=mission.id,
                target=mission.target,
            )
        except Exception:
            logger.debug("Failed to emit timeout event for %s", mission.id)

        try:
            await send_notification(
                title=f"Mission Timed Out: {mission.target}",
                message=f"Mission {mission.id[:8]} exceeded {max_hours}h and was stopped.",
                priority="high",
                tags=["warning"],
            )
        except Exception:
            logger.debug("Failed to send timeout notification for %s", mission.id)

    logger.info("Timed out %d mission(s) exceeding %d hours", len(missions), max_hours)
    return len(missions)


async def cleanup_orphaned_findings(session) -> int:
    """Remove findings whose target no longer exists."""
    from app.models.finding import Finding
    from app.models.target import Target

    result = await session.execute(delete(Finding).where(~Finding.target_id.in_(select(Target.id))))
    await session.commit()
    count = result.rowcount  # type: ignore[union-attr]
    if count:
        logger.info("Removed %d orphaned findings", count)
    return count


async def log_table_sizes(session) -> dict[str, int]:
    """Log approximate row counts for key tables."""
    tables = ["missions", "targets", "findings", "exploits", "audit_logs", "job_queue"]
    sizes: dict[str, int] = {}
    for table in tables:
        try:
            result = await session.execute(
                text("SELECT reltuples::bigint FROM pg_class WHERE relname = :tbl"),
                {"tbl": table},
            )
            row = result.scalar()
            sizes[table] = max(int(row or 0), 0)
        except Exception:
            sizes[table] = -1
    logger.info("Table sizes (approx rows): %s", sizes)
    return sizes


async def analyze_tables(session) -> None:
    """Run ANALYZE on key tables to update planner statistics."""
    tables = ["missions", "targets", "findings", "exploits"]
    for table in tables:
        try:
            await session.execute(text(f"ANALYZE {table}"))  # noqa: S608
        except Exception as e:
            logger.debug("ANALYZE %s failed: %s", table, e)
    logger.info("Updated statistics for %d tables", len(tables))


async def run_all_cleanup() -> dict[str, int]:
    """Run all cleanup tasks. Intended for periodic scheduling."""
    from app.core.database import async_session_maker
    from app.services.tools.sandbox import get_sandbox_pool

    results: dict[str, int] = {}

    async with async_session_maker() as session:
        results["expired_cache"] = await cleanup_expired_cache(session)
        results["old_cache_entries"] = await cleanup_old_cache_entries(session)
        results["completed_jobs"] = await cleanup_completed_jobs(session)
        results["expired_sessions"] = await cleanup_expired_sessions(session)

    sandbox_pool = get_sandbox_pool()
    results["orphaned_sandboxes"] = await cleanup_orphaned_sandboxes(sandbox_pool)

    total = sum(results.values())
    if total:
        logger.info("Cleanup summary: %s", results)
    return results


async def run_daily_maintenance() -> dict[str, int]:
    """Run heavier daily maintenance tasks (audit log pruning, DB health)."""
    from app.core.database import async_session_maker

    results: dict[str, int] = {}

    async with async_session_maker() as session:
        results["old_audit_logs"] = await cleanup_old_audit_logs(session)
        results["orphaned_findings"] = await cleanup_orphaned_findings(session)
        await log_table_sizes(session)
        await analyze_tables(session)

    logger.info("Daily maintenance summary: %s", results)
    return results


async def run_mission_timeout_check() -> int:
    """Check and mark timed-out missions."""
    from app.core.database import async_session_maker

    async with async_session_maker() as session:
        return await check_mission_timeouts(session)
