"""System maintenance tasks, importable by core and scheduler without worker dependency."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def run_all_cleanup() -> dict[str, int]:
    """Run all cleanup tasks. Intended for periodic scheduling."""
    from spectra_platform.core.database import async_session_maker
    from spectra_platform.services.maintenance_cleanup import (
        cleanup_audit_logs,
        cleanup_completed_jobs,
        cleanup_expired_cache,
        cleanup_old_cache_entries,
        cleanup_old_missions,
        cleanup_orphaned_sandboxes,
        cleanup_transient_mission_artifacts,
    )
    from spectra_platform.services.tools.sandbox import get_sandbox_pool

    results: dict[str, int] = {}

    async with async_session_maker() as session:
        results["expired_cache"] = await cleanup_expired_cache(session)
        results["old_cache_entries"] = await cleanup_old_cache_entries(session)
        results["completed_jobs"] = await cleanup_completed_jobs(session)
        results["audit_logs"] = await cleanup_audit_logs(session)
        results["expired_missions"] = await cleanup_old_missions(session)

    sandbox_pool = get_sandbox_pool()
    results["orphaned_sandboxes"] = await cleanup_orphaned_sandboxes(sandbox_pool)
    results["transient_mission_artifacts"] = await cleanup_transient_mission_artifacts()

    total = sum(results.values())
    if total:
        logger.info("Cleanup summary: %s", results)
    return results
