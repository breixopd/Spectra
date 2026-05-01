"""Tests for dead-letter queue — handle_job_failure and list_dead_letter_jobs."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture()
def queue():
    """Create a PostgresJobQueue without touching the real DB."""
    from spectra_platform.infrastructure.queue import PostgresJobQueue

    q = object.__new__(PostgresJobQueue)
    q.queue_name = "default"
    return q


def _mock_session_ctx(session):
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _make_job(retry_count: int = 0, max_retries: int = 3, status: str = "in_progress"):
    job = MagicMock()
    job.retry_count = retry_count
    job.max_retries = max_retries
    job.status = status
    job.error = None
    job.completed_at = None
    return job


# --- handle_job_failure ---


@pytest.mark.asyncio
async def test_handle_job_failure_increments_retry_count(queue):
    job = _make_job(retry_count=0, max_retries=3)
    session = AsyncMock()
    session.get = AsyncMock(return_value=job)
    session.commit = AsyncMock()

    with patch("spectra_platform.infrastructure.queue.async_session_maker", return_value=_mock_session_ctx(session)):
        await queue.handle_job_failure("job-1", "some error")

    assert job.retry_count == 1


@pytest.mark.asyncio
async def test_handle_job_failure_requeues_under_max_retries(queue):
    job = _make_job(retry_count=1, max_retries=3)
    session = AsyncMock()
    session.get = AsyncMock(return_value=job)
    session.commit = AsyncMock()

    with patch("spectra_platform.infrastructure.queue.async_session_maker", return_value=_mock_session_ctx(session)):
        await queue.handle_job_failure("job-2", "transient error")

    assert job.status == "pending"
    assert job.error == "transient error"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_job_failure_moves_to_dead_letter_at_max(queue):
    job = _make_job(retry_count=2, max_retries=3)
    session = AsyncMock()
    session.get = AsyncMock(return_value=job)
    session.commit = AsyncMock()

    with patch("spectra_platform.infrastructure.queue.async_session_maker", return_value=_mock_session_ctx(session)):
        await queue.handle_job_failure("job-3", "persistent error")

    assert job.status == "dead_letter"
    assert job.completed_at is not None
    assert job.error == "persistent error"


@pytest.mark.asyncio
async def test_handle_job_failure_noop_for_missing_job(queue):
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    session.commit = AsyncMock()

    with patch("spectra_platform.infrastructure.queue.async_session_maker", return_value=_mock_session_ctx(session)):
        await queue.handle_job_failure("nonexistent", "err")

    session.commit.assert_not_awaited()


# --- list_dead_letter_jobs ---


@pytest.mark.asyncio
async def test_list_dead_letter_jobs_returns_dead_letter(queue):
    dead_job = _make_job(status="dead_letter")
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [dead_job]

    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)

    with patch("spectra_platform.infrastructure.queue.async_session_maker", return_value=_mock_session_ctx(session)):
        jobs = await queue.list_dead_letter_jobs()

    assert len(jobs) == 1
    assert jobs[0].status == "dead_letter"


@pytest.mark.asyncio
async def test_list_dead_letter_jobs_empty_when_none(queue):
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []

    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)

    with patch("spectra_platform.infrastructure.queue.async_session_maker", return_value=_mock_session_ctx(session)):
        jobs = await queue.list_dead_letter_jobs()

    assert jobs == []
