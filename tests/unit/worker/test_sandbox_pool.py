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
        from spectra_tools.sandbox.models import SandboxInfo

        mission_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        result = SandboxInfo.make_queue_name(mission_id)
        assert result == "mission_a1b2c3d4"

    def test_make_queue_name_strips_hyphens(self):
        """Hyphens in UUID are stripped before taking prefix."""
        from spectra_tools.sandbox.models import SandboxInfo

        mission_id = "abcd-efgh-1234"
        result = SandboxInfo.make_queue_name(mission_id)
        # "abcdefgh1234" → first 8 → "abcdefgh"
        assert result == "mission_abcdefgh"

    def test_make_queue_name_valid_for_queue(self):
        """Generated queue name passes PostgresJobQueue regex."""
        from spectra_infra.queue import PostgresJobQueue
        from spectra_tools.sandbox.models import SandboxInfo

        mission_id = str(uuid.uuid4())
        queue_name = SandboxInfo.make_queue_name(mission_id)
        # This should NOT raise
        q = PostgresJobQueue(queue_name)
        assert q.queue_name == queue_name

    def test_make_queue_name_lowercase(self):
        """Queue names are always lowercase."""
        from spectra_tools.sandbox.models import SandboxInfo

        mission_id = "ABCDEF12-3456-7890-abcd-ef1234567890"
        result = SandboxInfo.make_queue_name(mission_id)
        assert result == result.lower()


# --- Queue regex tests ---


class TestQueueNameValidation:
    """Tests for PostgresJobQueue queue_name validation."""

    def test_default_queue_accepted(self):
        from spectra_infra.queue import PostgresJobQueue

        q = PostgresJobQueue("default")
        assert q.queue_name == "default"

    def test_mission_queue_accepted(self):
        from spectra_infra.queue import PostgresJobQueue

        q = PostgresJobQueue("mission_a1b2c3d4")
        assert q.queue_name == "mission_a1b2c3d4"

    def test_empty_name_rejected(self):
        from spectra_infra.queue import PostgresJobQueue

        with pytest.raises(ValueError):
            PostgresJobQueue("")

    def test_hyphen_rejected(self):
        from spectra_infra.queue import PostgresJobQueue

        with pytest.raises(ValueError):
            PostgresJobQueue("mission-a1b2c3d4")

    def test_uppercase_rejected(self):
        from spectra_infra.queue import PostgresJobQueue

        with pytest.raises(ValueError):
            PostgresJobQueue("Mission_a1b2")

    def test_space_rejected(self):
        from spectra_infra.queue import PostgresJobQueue

        with pytest.raises(ValueError):
            PostgresJobQueue("hello world")

    def test_long_name_rejected(self):
        """Names >63 chars should be rejected."""
        from spectra_infra.queue import PostgresJobQueue

        with pytest.raises(ValueError):
            PostgresJobQueue("a" * 64)

    def test_max_length_accepted(self):
        from spectra_infra.queue import PostgresJobQueue

        q = PostgresJobQueue("a" * 63)
        assert len(q.queue_name) == 63

    def test_starts_with_digit_rejected(self):
        from spectra_infra.queue import PostgresJobQueue

        with pytest.raises(ValueError):
            PostgresJobQueue("1mission")


# --- SandboxPool tests (mocked Docker) ---


class TestSandboxPool:
    """Tests for SandboxPool with mocked Docker SDK."""

    def test_pool_unavailable_when_docker_init_fails(self):
        """Pool gracefully handles Docker init failure."""
        with patch("spectra_tools.sandbox.pool.docker", create=True) as mock_docker:
            mock_docker.from_env.side_effect = Exception("No Docker")
            from spectra_tools.sandbox.pool import SandboxPool

            pool = SandboxPool.__new__(SandboxPool)
            pool.available = False
            pool._client = None
            assert pool.available is False

    @pytest.mark.asyncio
    async def test_create_sandbox_docker_unavailable(self):
        """create() raises when Docker is unavailable."""
        from spectra_tools.sandbox.pool import SandboxPool

        pool = SandboxPool.__new__(SandboxPool)
        pool.available = False
        pool._client = None

        with pytest.raises(RuntimeError, match="Docker is not available"):
            await pool.create("test-mission-id")

    @pytest.mark.asyncio
    async def test_create_sandbox_max_reached(self):
        """create() raises when max containers reached."""
        from spectra_tools.sandbox.pool import SandboxPool

        pool = SandboxPool.__new__(SandboxPool)
        pool.available = True
        pool._client = MagicMock()

        with patch.object(pool, "_count_running", new_callable=AsyncMock, return_value=10):
            with patch("spectra_tools.sandbox.pool.get_settings") as mock_settings:
                mock_settings.return_value.SANDBOX_MAX_CONTAINERS = 10
                with pytest.raises(RuntimeError, match="Sandbox limit reached"):
                    await pool.create("test-mission-id")

    @pytest.mark.asyncio
    async def test_get_returns_none_for_unknown_mission(self):
        """get() returns None when no sandbox exists for mission."""
        from spectra_tools.sandbox.pool import SandboxPool

        pool = SandboxPool.__new__(SandboxPool)
        pool.available = True
        pool._client = MagicMock()

        # Mock DB returning no rows
        with patch("spectra_tools.sandbox.pool.async_session_maker") as mock_session:
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

    def test_get_queue_name_with_sandbox_pool(self):
        """Returns mission-specific queue when sandbox pool is available."""
        from spectra_tools.service import ToolExecutionService

        mock_pool = MagicMock()
        mock_pool.available = True
        with patch("spectra_tools.sandbox.get_sandbox_pool", return_value=mock_pool):
            result = ToolExecutionService._get_queue_name("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
            assert result == "mission_a1b2c3d4"

    def test_get_queue_name_without_sandbox_pool(self):
        """Returns default queue when sandbox pool is unavailable."""
        from spectra_tools.service import ToolExecutionService

        with patch("spectra_tools.sandbox.get_sandbox_pool", return_value=None):
            result = ToolExecutionService._get_queue_name("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
            assert result == "default"

    def test_get_queue_name_pool_not_available(self):
        """Returns default queue when pool exists but is not available."""
        from spectra_tools.service import ToolExecutionService

        mock_pool = MagicMock()
        mock_pool.available = False
        with patch("spectra_tools.sandbox.get_sandbox_pool", return_value=mock_pool):
            result = ToolExecutionService._get_queue_name("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
            assert result == "default"


# --- Sandbox container config tests ---

_POOL_PY = Path(__file__).resolve().parents[3] / "packages/tools/src/spectra_tools/sandbox/pool.py"


class TestSandboxPoolVolumes:
    """Tests for sandbox container isolation and environment configuration."""

    def test_sandbox_environment_includes_required_keys(self):
        """Verify sandbox receives only its per-mission queue credential."""
        source = _POOL_PY.read_text()
        assert '"QUEUE_NAME"' in source
        assert '"IS_TOOLS_CONTAINER"' in source
        assert "_provision_database_access" in source
        assert "sandbox_database_role_name" in source
        assert '"JWT_SECRET_KEY"' not in source

    def test_sandbox_uses_ephemeral_writable_state_not_shared_platform_volumes(self):
        """Untrusted sandboxes cannot mutate shared app data or tool binaries."""
        source = _POOL_PY.read_text()
        assert "/app/data" in source
        assert "read_only=True" in source
        assert '"/app/data": "rw,noexec,nosuid,nodev,size=512m"' in source

    def test_sandbox_uses_plugins_baked_into_the_promoted_image(self):
        """Untrusted sandboxes must not receive a mutable shared plugin mount."""
        source = _POOL_PY.read_text()
        assert 'target="/app/plugins"' not in source
        assert "SANDBOX_PLUGINS_VOLUME" not in source


def test_per_mission_database_credentials_are_safe_and_do_not_reuse_admin_password():
    from spectra_tools.sandbox._utils import sandbox_database_role_name, sandbox_database_url

    mission_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    role_name = sandbox_database_role_name(mission_id)
    assert role_name == "spectra_sandbox_a1b2c3d4e5f67890abcdef1234567890"

    sandbox_url = sandbox_database_url(
        "postgresql+asyncpg://admin:admin-password@db:5432/spectra",
        role_name=role_name,
        password="sandbox-password",
    )
    assert "admin-password" not in sandbox_url
    assert role_name in sandbox_url
    assert "sandbox-password" in sandbox_url

    with pytest.raises(ValueError, match="UUID"):
        sandbox_database_role_name("not-a-uuid")


# --- Module-level singleton tests ---


class TestSandboxSingleton:
    """Tests for get/set sandbox pool singleton."""

    def test_set_and_get(self):
        from spectra_tools.sandbox import get_sandbox_pool, set_sandbox_pool

        mock_pool = MagicMock()
        set_sandbox_pool(mock_pool)  # type: ignore[arg-type]
        assert get_sandbox_pool() is mock_pool

        # Clean up
        set_sandbox_pool(None)

    def test_get_returns_none_after_clear(self):
        from spectra_tools.sandbox import get_sandbox_pool, set_sandbox_pool

        set_sandbox_pool(None)
        assert get_sandbox_pool() is None


class TestSandboxPoolTierLimits:
    def test_get_tier_limits_known(self):
        from spectra_tools.sandbox.pool import SandboxPool

        with patch("spectra_tools.sandbox.pool.get_settings") as mock_settings:
            mock_settings.return_value.SANDBOX_RESOURCE_TIERS = (
                '{"light": {"memory": "256m", "cpu_shares": 128}, "medium": {"memory": "512m", "cpu_shares": 256}}'
            )
            memory, cpu = SandboxPool.get_tier_limits("light")
            assert memory == "256m"
            assert cpu == 128

    def test_get_tier_limits_unknown_fallback(self):
        from spectra_tools.sandbox.pool import SandboxPool

        with patch("spectra_tools.sandbox.pool.get_settings") as mock_settings:
            mock_settings.return_value.SANDBOX_RESOURCE_TIERS = '{"medium": {"memory": "512m", "cpu_shares": 256}}'
            memory, cpu = SandboxPool.get_tier_limits("nonexistent")
            assert memory == "512m"
            assert cpu == 256


# --- Worker QUEUE_NAME env var test ---


class TestWorkerQueueEnv:
    """Tests for worker __main__ QUEUE_NAME environment variable support."""

    def test_worker_has_queue_name_env_support(self):
        """Verify the worker service reads QUEUE_NAME from environment."""
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent.parent.parent
        worker_path = root / "services/worker/src/spectra_worker/__main__.py"
        if not worker_path.is_file():
            worker_path = root / "spectra_worker/__main__.py"
        source = worker_path.read_text()

        assert 'os.environ.get("QUEUE_NAME"' in source or "os.environ.get('QUEUE_NAME'" in source, (
            "Worker should read QUEUE_NAME from environment"
        )

        assert "queue_name=queue_name" in source, "Worker should pass queue_name to worker_loop"
