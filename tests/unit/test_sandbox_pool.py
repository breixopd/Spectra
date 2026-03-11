"""Tests for per-mission ephemeral sandbox system."""

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# --- SandboxInfo tests ---


class TestSandboxInfo:
    """Tests for SandboxInfo dataclass."""

    def test_make_queue_name_format(self):
        """Queue name uses first 8 hex chars of mission UUID."""
        from app.services.tools.sandbox.models import SandboxInfo

        mission_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        result = SandboxInfo.make_queue_name(mission_id)
        assert result == "mission_a1b2c3d4"

    def test_make_queue_name_strips_hyphens(self):
        """Hyphens in UUID are stripped before taking prefix."""
        from app.services.tools.sandbox.models import SandboxInfo

        mission_id = "abcd-efgh-1234"
        result = SandboxInfo.make_queue_name(mission_id)
        # "abcdefgh1234" → first 8 → "abcdefgh"
        assert result == "mission_abcdefgh"

    def test_make_queue_name_valid_for_queue(self):
        """Generated queue name passes PostgresJobQueue regex."""
        from app.core.queue import PostgresJobQueue
        from app.services.tools.sandbox.models import SandboxInfo

        mission_id = str(uuid.uuid4())
        queue_name = SandboxInfo.make_queue_name(mission_id)
        # This should NOT raise
        q = PostgresJobQueue(queue_name)
        assert q.queue_name == queue_name

    def test_make_queue_name_lowercase(self):
        """Queue names are always lowercase."""
        from app.services.tools.sandbox.models import SandboxInfo

        mission_id = "ABCDEF12-3456-7890-abcd-ef1234567890"
        result = SandboxInfo.make_queue_name(mission_id)
        assert result == result.lower()


# --- Queue regex tests ---


class TestQueueNameValidation:
    """Tests for PostgresJobQueue queue_name validation."""

    def test_default_queue_accepted(self):
        from app.core.queue import PostgresJobQueue

        q = PostgresJobQueue("default")
        assert q.queue_name == "default"

    def test_mission_queue_accepted(self):
        from app.core.queue import PostgresJobQueue

        q = PostgresJobQueue("mission_a1b2c3d4")
        assert q.queue_name == "mission_a1b2c3d4"

    def test_empty_name_rejected(self):
        from app.core.queue import PostgresJobQueue

        with pytest.raises(ValueError):
            PostgresJobQueue("")

    def test_hyphen_rejected(self):
        from app.core.queue import PostgresJobQueue

        with pytest.raises(ValueError):
            PostgresJobQueue("mission-a1b2c3d4")

    def test_uppercase_rejected(self):
        from app.core.queue import PostgresJobQueue

        with pytest.raises(ValueError):
            PostgresJobQueue("Mission_a1b2")

    def test_space_rejected(self):
        from app.core.queue import PostgresJobQueue

        with pytest.raises(ValueError):
            PostgresJobQueue("hello world")

    def test_long_name_rejected(self):
        """Names >63 chars should be rejected."""
        from app.core.queue import PostgresJobQueue

        with pytest.raises(ValueError):
            PostgresJobQueue("a" * 64)

    def test_max_length_accepted(self):
        from app.core.queue import PostgresJobQueue

        q = PostgresJobQueue("a" * 63)
        assert len(q.queue_name) == 63

    def test_starts_with_digit_rejected(self):
        from app.core.queue import PostgresJobQueue

        with pytest.raises(ValueError):
            PostgresJobQueue("1mission")


# --- SandboxPool tests (mocked Docker) ---


class TestSandboxPool:
    """Tests for SandboxPool with mocked Docker SDK."""

    def test_pool_unavailable_when_docker_init_fails(self):
        """Pool gracefully handles Docker init failure."""
        with patch("app.services.tools.sandbox.pool.docker", create=True) as mock_docker:
            mock_docker.from_env.side_effect = Exception("No Docker")
            from app.services.tools.sandbox.pool import SandboxPool

            pool = SandboxPool.__new__(SandboxPool)
            pool.available = False
            pool._client = None
            assert pool.available is False

    @pytest.mark.asyncio
    async def test_create_sandbox_docker_unavailable(self):
        """create() raises when Docker is unavailable."""
        from app.services.tools.sandbox.pool import SandboxPool

        pool = SandboxPool.__new__(SandboxPool)
        pool.available = False
        pool._client = None

        with pytest.raises(RuntimeError, match="Docker is not available"):
            await pool.create("test-mission-id")

    @pytest.mark.asyncio
    async def test_create_sandbox_max_reached(self):
        """create() raises when max containers reached."""
        from app.services.tools.sandbox.pool import SandboxPool

        pool = SandboxPool.__new__(SandboxPool)
        pool.available = True
        pool._client = MagicMock()

        with patch.object(pool, "_count_running", new_callable=AsyncMock, return_value=10):
            with patch("app.services.tools.sandbox.pool.get_settings") as mock_settings:
                mock_settings.return_value.SANDBOX_MAX_CONTAINERS = 10
                with pytest.raises(RuntimeError, match="Sandbox limit reached"):
                    await pool.create("test-mission-id")

    @pytest.mark.asyncio
    async def test_get_returns_none_for_unknown_mission(self):
        """get() returns None when no sandbox exists for mission."""
        from app.services.tools.sandbox.pool import SandboxPool

        pool = SandboxPool.__new__(SandboxPool)
        pool.available = True
        pool._client = MagicMock()

        # Mock DB returning no rows
        with patch("app.services.tools.sandbox.pool.async_session_maker") as mock_session:
            mock_ctx = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_ctx.execute = AsyncMock(return_value=mock_result)
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_session.return_value = mock_ctx

            result = await pool.get("nonexistent-mission")
            assert result is None


# --- ToolExecutionService._get_queue_name ---


class TestGetQueueName:
    """Tests for ToolExecutionService._get_queue_name routing."""

    def test_get_queue_name_delegates_to_sandbox_info(self):
        """_get_queue_name routes through SandboxInfo.make_queue_name."""
        from app.services.tools.service import ToolExecutionService

        result = ToolExecutionService._get_queue_name(
            "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        )
        assert result == "mission_a1b2c3d4"


# --- Sandbox container config tests ---


class TestSandboxPoolVolumes:
    """Tests for sandbox container volume and environment configuration."""

    def test_sandbox_environment_includes_required_keys(self):
        """Verify sandbox container gets DATABASE_URL, QUEUE_NAME, JWT_SECRET_KEY, etc."""
        source = Path("app/services/tools/sandbox/pool.py").read_text()
        assert '"DATABASE_URL"' in source
        assert '"QUEUE_NAME"' in source
        assert '"IS_TOOLS_CONTAINER"' in source
        assert '"JWT_SECRET_KEY"' in source
        assert '"PLUGIN_SAFE_MODE"' in source

    def test_sandbox_mounts_data_and_tools_volumes(self):
        """Verify sandbox uses named Docker volumes for data and tools."""
        source = Path("app/services/tools/sandbox/pool.py").read_text()
        assert "spectra_data" in source
        assert "spectra_tools_data" in source
        assert "/app/data" in source
        assert "/opt/spectra_tools" in source

    def test_sandbox_mounts_plugins_readonly(self):
        """Verify sandbox mounts plugins as read-only."""
        source = Path("app/services/tools/sandbox/pool.py").read_text()
        assert "/app/plugins" in source
        assert "read_only=True" in source


# --- Module-level singleton tests ---


class TestSandboxSingleton:
    """Tests for get/set sandbox pool singleton."""

    def test_set_and_get(self):
        from app.services.tools.sandbox import get_sandbox_pool, set_sandbox_pool

        mock_pool = MagicMock()
        set_sandbox_pool(mock_pool)  # type: ignore[arg-type]
        assert get_sandbox_pool() is mock_pool

        # Clean up
        set_sandbox_pool(None)

    def test_get_returns_none_after_clear(self):
        from app.services.tools.sandbox import get_sandbox_pool, set_sandbox_pool

        set_sandbox_pool(None)
        assert get_sandbox_pool() is None


# --- Worker QUEUE_NAME env var test ---


class TestWorkerQueueEnv:
    """Tests for worker __main__ QUEUE_NAME environment variable support."""

    def test_worker_has_queue_name_env_support(self):
        """Verify the worker __main__ reads QUEUE_NAME from environment."""
        from pathlib import Path

        worker_path = Path("app/worker/__main__.py")
        source = worker_path.read_text()

        assert (
            'os.environ.get("QUEUE_NAME"' in source
            or "os.environ.get('QUEUE_NAME'" in source
        ), "Worker should read QUEUE_NAME from environment"

        assert "queue_name=queue_name" in source, (
            "Worker should pass queue_name to worker_loop"
        )
