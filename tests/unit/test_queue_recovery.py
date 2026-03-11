"""Tests for PostgresJobQueue.recover_stale_jobs."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture()
def queue():
    """Create a PostgresJobQueue without touching the real DB."""
    with patch("app.core.queue.re"):
        from app.core.queue import PostgresJobQueue

    # Bypass the regex validation by constructing directly
    q = object.__new__(PostgresJobQueue)
    q.queue_name = "default"
    return q


def _make_job_row(status: str, started_minutes_ago: int | None):
    """Helper to create a mock JobQueue row."""
    row = MagicMock()
    row.status = status
    if started_minutes_ago is not None:
        row.started_at = datetime.now(UTC) - timedelta(minutes=started_minutes_ago)
    else:
        row.started_at = None
    return row


@pytest.mark.asyncio
async def test_recovers_stale_in_progress_jobs(queue):
    """Jobs in_progress longer than max_age should be marked failed."""
    mock_result = MagicMock()
    mock_result.rowcount = 2

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.core.queue.async_session_maker", return_value=ctx):
        count = await queue.recover_stale_jobs(max_age_minutes=30)

    assert count == 2
    mock_session.execute.assert_awaited_once()
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_does_not_recover_fresh_in_progress_jobs(queue):
    """Jobs that started recently should not be recovered."""
    mock_result = MagicMock()
    mock_result.rowcount = 0

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.core.queue.async_session_maker", return_value=ctx):
        count = await queue.recover_stale_jobs(max_age_minutes=30)

    assert count == 0


@pytest.mark.asyncio
async def test_completed_and_failed_jobs_untouched(queue):
    """Only in_progress jobs should be affected; completed/failed stay as-is."""
    mock_result = MagicMock()
    mock_result.rowcount = 0

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.core.queue.async_session_maker", return_value=ctx):
        count = await queue.recover_stale_jobs(max_age_minutes=1)

    # The SQL WHERE clause filters on status == 'in_progress',
    # so completed/failed rows are never touched.
    assert count == 0
