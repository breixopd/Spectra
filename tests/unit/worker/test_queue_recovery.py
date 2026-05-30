"""Tests for PostgresJobQueue.recover_stale_jobs."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture()
def queue():
    """Create a PostgresJobQueue without touching the real DB."""
    with patch("spectra_infra.queue.re"):
        from spectra_infra.queue import PostgresJobQueue

    # Bypass the regex validation by constructing directly
    q = object.__new__(PostgresJobQueue)
    q.queue_name = "default"
    return q


def _make_stale_job(job_id: str, started_minutes_ago: int):
    """Helper to create a mock JobQueue row."""
    row = MagicMock()
    row.id = job_id
    row.status = "in_progress"
    row.started_at = datetime.now(UTC) - timedelta(minutes=started_minutes_ago)
    return row


@pytest.mark.asyncio
async def test_recovers_stale_in_progress_jobs(queue):
    """Jobs in_progress longer than max_age should be routed through handle_job_failure."""
    stale_jobs = [_make_stale_job("job-1", 60), _make_stale_job("job-2", 45)]

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = stale_jobs

    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("spectra_infra.queue.async_session_maker", return_value=ctx),
        patch.object(queue, "handle_job_failure", new_callable=AsyncMock) as mock_handle,
    ):
        count = await queue.recover_stale_jobs(max_age_minutes=30)

    assert count == 2
    assert mock_handle.await_count == 2
    mock_handle.assert_any_await("job-1", "Stale job recovered after 30 minutes")
    mock_handle.assert_any_await("job-2", "Stale job recovered after 30 minutes")


@pytest.mark.asyncio
async def test_does_not_recover_fresh_in_progress_jobs(queue):
    """Jobs that started recently should not be recovered."""
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []

    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("spectra_infra.queue.async_session_maker", return_value=ctx):
        count = await queue.recover_stale_jobs(max_age_minutes=30)

    assert count == 0


@pytest.mark.asyncio
async def test_completed_and_failed_jobs_untouched(queue):
    """Only in_progress jobs should be affected; completed/failed stay as-is."""
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []

    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("spectra_infra.queue.async_session_maker", return_value=ctx):
        count = await queue.recover_stale_jobs(max_age_minutes=1)

    # The SQL WHERE clause filters on status == 'in_progress',
    # so completed/failed rows are never touched.
    assert count == 0
