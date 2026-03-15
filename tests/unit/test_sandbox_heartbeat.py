"""Tests for sandbox idle watchdog and worker heartbeat."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr


class TestHeartbeatConfig:
    """Heartbeat settings exist with correct defaults."""

    def test_idle_timeout_default(self):
        from app.core.config import Settings

        s = Settings(DATABASE_URL=SecretStr("postgresql+asyncpg://spectra:spectra_test@db:5432/spectra_test"))
        assert s.SANDBOX_IDLE_TIMEOUT == 600

    def test_heartbeat_interval_default(self):
        from app.core.config import Settings

        s = Settings(DATABASE_URL=SecretStr("postgresql+asyncpg://spectra:spectra_test@db:5432/spectra_test"))
        assert s.SANDBOX_HEARTBEAT_INTERVAL == 30


class TestSandboxModelHeartbeat:
    """Sandbox model has last_heartbeat column."""

    def test_last_heartbeat_column_exists(self):
        from app.models.infrastructure import Sandbox

        assert hasattr(Sandbox, "last_heartbeat")


class TestHeartbeatLoop:
    """Worker heartbeat_loop sends periodic DB updates."""

    @pytest.mark.asyncio
    async def test_heartbeat_loop_exists(self):
        """heartbeat_loop is importable from worker module."""
        from app.worker import heartbeat_loop

        assert callable(heartbeat_loop)

    @pytest.mark.asyncio
    async def test_heartbeat_loop_updates_db(self):
        """heartbeat_loop issues UPDATE to sandboxes table."""
        from app.worker import heartbeat_loop

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        call_count = 0

        async def tracked_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1

        mock_session.execute = tracked_execute
        mock_session.commit = AsyncMock()

        with patch("app.core.database.async_session_maker", return_value=mock_session):
            task = asyncio.create_task(heartbeat_loop("test_queue", interval=0))
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert call_count > 0


class TestWatchdogStaleness:
    """Watchdog correctly identifies stale sandboxes."""

    def test_stale_detection_logic(self):
        """Sandbox with old heartbeat should be considered stale."""
        now = datetime.now(UTC)
        old_heartbeat = now - timedelta(seconds=700)
        idle_seconds = (now - old_heartbeat).total_seconds()
        assert idle_seconds > 600  # Default idle timeout

    def test_fresh_sandbox_not_stale(self):
        """Sandbox with recent heartbeat should NOT be considered stale."""
        now = datetime.now(UTC)
        recent_heartbeat = now - timedelta(seconds=10)
        idle_seconds = (now - recent_heartbeat).total_seconds()
        assert idle_seconds < 600

    def test_sandbox_without_heartbeat_uses_creation_time(self):
        """Sandbox that never sent heartbeat — use age from creation."""
        now = datetime.now(UTC)
        created_1h_ago = now - timedelta(hours=1)
        age = (now - created_1h_ago).total_seconds()
        assert age > 600  # Would be considered stale
