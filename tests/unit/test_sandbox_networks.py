"""Tests for per-sandbox Docker network isolation."""


class TestNetworkIsolation:
    """Pool creates/destroys isolated networks when enabled."""

    def test_sandbox_info_has_network_id(self):
        from app.services.tools.sandbox.models import SandboxInfo

        info = SandboxInfo(
            container_id="abc",
            container_name="test",
            mission_id="m1",
            queue_name="q1",
            status="running",
            image="img",
            network_id="net_123",
        )
        assert info.network_id == "net_123"

    def test_sandbox_info_network_id_default_none(self):
        from app.services.tools.sandbox.models import SandboxInfo

        info = SandboxInfo(
            container_id="abc",
            container_name="test",
            mission_id="m1",
            queue_name="q1",
            status="running",
            image="img",
        )
        assert info.network_id is None

    def test_sandbox_model_has_network_id_column(self):
        from app.models.infrastructure import Sandbox

        assert hasattr(Sandbox, "network_id")

    def test_config_has_network_isolation_setting(self):
        from pydantic import SecretStr

        from app.core.config import Settings

        s = Settings(
            DATABASE_URL=SecretStr("sqlite:///test.db"),
            SANDBOX_NETWORK_ISOLATION=False,
        )
        assert s.SANDBOX_NETWORK_ISOLATION is False

    def test_config_network_isolation_default_true(self):
        from pydantic import SecretStr

        from app.core.config import Settings

        s = Settings(DATABASE_URL=SecretStr("sqlite:///test.db"))
        assert s.SANDBOX_NETWORK_ISOLATION is True
