"""Tests for cleanup worker tasks."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_execute_result(rowcount: int):
    result = MagicMock()
    result.rowcount = rowcount
    return result


# --- cleanup_expired_cache ---


@pytest.mark.asyncio
async def test_cleanup_expired_cache_purges_entries():
    from app.services.maintenance_cleanup import cleanup_expired_cache

    session = AsyncMock()
    session.execute = AsyncMock(return_value=_mock_execute_result(5))
    session.commit = AsyncMock()

    count = await cleanup_expired_cache(session)
    assert count == 5
    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_expired_cache_zero_when_none():
    from app.services.maintenance_cleanup import cleanup_expired_cache

    session = AsyncMock()
    session.execute = AsyncMock(return_value=_mock_execute_result(0))
    session.commit = AsyncMock()

    count = await cleanup_expired_cache(session)
    assert count == 0


# --- cleanup_orphaned_sandboxes ---


@pytest.mark.asyncio
async def test_cleanup_orphaned_sandboxes_finds_orphans():
    from app.services.maintenance_cleanup import cleanup_orphaned_sandboxes

    pool = MagicMock()
    pool.available = True
    pool.cleanup_all = AsyncMock(return_value=3)

    count = await cleanup_orphaned_sandboxes(pool)
    assert count == 3
    pool.cleanup_all.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_orphaned_sandboxes_skips_when_unavailable():
    from app.services.maintenance_cleanup import cleanup_orphaned_sandboxes

    pool = MagicMock()
    pool.available = False

    count = await cleanup_orphaned_sandboxes(pool)
    assert count == 0


@pytest.mark.asyncio
async def test_cleanup_orphaned_sandboxes_skips_when_no_pool():
    from app.services.maintenance_cleanup import cleanup_orphaned_sandboxes

    count = await cleanup_orphaned_sandboxes(None)
    assert count == 0


# --- cleanup_completed_jobs ---


@pytest.mark.asyncio
async def test_cleanup_completed_jobs_removes_old():
    from app.services.maintenance_cleanup import cleanup_completed_jobs

    session = AsyncMock()
    session.execute = AsyncMock(return_value=_mock_execute_result(10))
    session.commit = AsyncMock()

    count = await cleanup_completed_jobs(session, max_age_days=30)
    assert count == 10
    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()


# --- run_all_cleanup ---


@pytest.mark.asyncio
async def test_run_all_cleanup_calls_all_functions():
    from app.services.maintenance import run_all_cleanup

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=_mock_execute_result(1))
    mock_session.commit = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    mock_pool = MagicMock()
    mock_pool.available = True
    mock_pool.cleanup_all = AsyncMock(return_value=2)

    mock_storage = MagicMock()
    mock_storage.list_objects = AsyncMock(return_value=[])
    mock_storage.delete = AsyncMock(return_value=True)

    with (
        patch("app.core.database.async_session_maker", return_value=ctx),
        patch("app.services.tools.sandbox.get_sandbox_pool", return_value=mock_pool),
        patch("app.services.storage.get_storage_service", return_value=mock_storage),
    ):
        results = await run_all_cleanup()

    assert "expired_cache" in results
    assert "old_cache_entries" in results
    assert "completed_jobs" in results
    assert "orphaned_sandboxes" in results
    assert results["orphaned_sandboxes"] == 2
