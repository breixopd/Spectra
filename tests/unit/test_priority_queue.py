"""Tests for priority queue ordering and per-user sandbox limits."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr


class TestPriorityConfig:
    """Priority queue settings exist with defaults."""

    def test_per_user_limit_default(self):
        from app.core.config import Settings
        s = Settings(DATABASE_URL=SecretStr("sqlite:///test.db"))
        assert s.SANDBOX_PER_USER_LIMIT == 3

    def test_default_priority_default(self):
        from app.core.config import Settings
        s = Settings(DATABASE_URL=SecretStr("sqlite:///test.db"))
        assert s.SANDBOX_DEFAULT_PRIORITY == 5


class TestJobQueuePriority:
    """JobQueue model has priority column."""

    def test_priority_column_exists(self):
        from app.models.infrastructure import JobQueue
        assert hasattr(JobQueue, "priority")

    def test_priority_default_is_five(self):
        from app.models.infrastructure import JobQueue
        col = JobQueue.__table__.c.priority
        assert col.default.arg == 5


class TestEnqueueWithPriority:
    """PostgresJobQueue.enqueue_job accepts priority."""

    @pytest.mark.asyncio
    async def test_enqueue_accepts_priority_param(self):
        """enqueue_job should accept _priority keyword argument."""
        import inspect

        from app.core.queue import PostgresJobQueue
        sig = inspect.signature(PostgresJobQueue.enqueue_job)
        assert "_priority" in sig.parameters

    @pytest.mark.asyncio
    async def test_enqueue_with_explicit_priority(self):
        from app.core.queue import PostgresJobQueue
        from app.models.infrastructure import JobQueue

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        # Mock the connection for NOTIFY
        mock_conn = AsyncMock()
        mock_raw_conn = AsyncMock()
        mock_raw_conn.driver_connection = AsyncMock()
        mock_conn.get_raw_connection = AsyncMock(return_value=mock_raw_conn)
        mock_session.connection = AsyncMock(return_value=mock_conn)

        captured_job = None

        def capture_add(obj):
            nonlocal captured_job
            if isinstance(obj, JobQueue):
                captured_job = obj

        mock_session.add = capture_add

        with patch("app.core.queue.async_session_maker", return_value=mock_session):
            q = PostgresJobQueue("default")
            await q.enqueue_job("test_fn", _priority=1)

        assert captured_job is not None
        assert captured_job.priority == 1


class TestSandboxUserIdColumn:
    """Sandbox model has user_id column for per-user limits."""

    def test_user_id_column_exists(self):
        from app.models.infrastructure import Sandbox
        assert hasattr(Sandbox, "user_id")

    def test_escalated_column_exists(self):
        from app.models.infrastructure import Sandbox
        assert hasattr(Sandbox, "escalated")
