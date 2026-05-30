"""Tests for spectra_api.services.system.settings_service.

Uses sys.modules pre-population to break remaining circular imports via
heavy ``spectra_api.api`` / router stubs where needed.
"""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _break_circular_import():
    """Pre-populate heavy modules so the import chain doesn't recurse."""
    stubs = {}
    for mod_name in (
        "spectra_api.api",
        "spectra_api.api.routers",
        "spectra_api.ui.pages",
    ):
        if mod_name not in sys.modules:
            stubs[mod_name] = sys.modules.setdefault(mod_name, MagicMock())
    yield
    for mod_name, stub in stubs.items():
        if sys.modules.get(mod_name) is stub:
            del sys.modules[mod_name]


def _mod():
    from spectra_api.services.system import settings_service

    return settings_service


class TestGetSandboxStatus:
    """Tests for get_sandbox_status()."""

    def _fn(self):
        return _mod().get_sandbox_status

    def test_pool_available(self):
        pool = MagicMock()
        pool.available = True
        with patch(
            "spectra_tools.sandbox.get_sandbox_pool",
            return_value=pool,
        ):
            status = self._fn()()
        assert status["available"] is True

    def test_pool_unavailable(self):
        pool = MagicMock()
        pool.available = False
        with patch(
            "spectra_tools.sandbox.get_sandbox_pool",
            return_value=pool,
        ):
            status = self._fn()()
        assert status["available"] is False

    def test_pool_none(self):
        with patch(
            "spectra_tools.sandbox.get_sandbox_pool",
            return_value=None,
        ):
            status = self._fn()()
        assert status["available"] is False

    def test_exception_returns_unavailable(self):
        with patch(
            "spectra_tools.sandbox.get_sandbox_pool",
            side_effect=RuntimeError("no docker"),
        ):
            status = self._fn()()
        assert status["available"] is False
        assert "not initialized" in status["message"]


class TestCollectGeneralDbSettings:
    """Tests for _collect_general_db_settings helper."""

    def _fn(self):
        return _mod()._collect_general_db_settings

    def _make_data(self, **kwargs):
        data = MagicMock()
        for k, v in kwargs.items():
            setattr(data, k, v)
        return data

    def test_maps_log_level(self):
        data = self._make_data(log_level="DEBUG")
        result = self._fn()(data, {"log_level"})
        assert "LOG_LEVEL" in result
        assert result["LOG_LEVEL"] == ("DEBUG", False)

    def test_maps_int_field(self):
        data = self._make_data(sandbox_max_containers=10)
        result = self._fn()(data, {"sandbox_max_containers"})
        assert result["SANDBOX_MAX_CONTAINERS"] == ("10", False)

    def test_skips_unset_fields(self):
        data = self._make_data(log_level="INFO")
        result = self._fn()(data, set())
        assert result == {}

    def test_nullable_empty_string(self):
        data = self._make_data(notification_webhook=None)
        result = self._fn()(data, {"notification_webhook"})
        assert result["NOTIFICATION_WEBHOOK"] == ("", False)

    def test_secret_field_flagged(self):
        data = self._make_data(s3_secret_key="secret123")
        result = self._fn()(data, {"s3_secret_key"})
        assert result["S3_SECRET_KEY"][1] is True

    def test_maps_billing_fields(self):
        data = self._make_data(
            payment_provider="stripe",
            stripe_publishable_key="pk_test_123",
            stripe_secret_key="sk_test_123",
            stripe_webhook_secret="whsec_123",
        )
        result = self._fn()(
            data,
            {"payment_provider", "stripe_publishable_key", "stripe_secret_key", "stripe_webhook_secret"},
        )
        assert result["PAYMENT_PROVIDER"] == ("stripe", False)
        assert result["STRIPE_PUBLISHABLE_KEY"] == ("pk_test_123", False)
        assert result["STRIPE_SECRET_KEY"] == ("sk_test_123", True)
        assert result["STRIPE_WEBHOOK_SECRET"] == ("whsec_123", True)


class TestApplySettingsUpdate:
    """Tests for apply_settings_update async function."""

    @pytest.mark.asyncio
    async def test_persists_and_commits(self):
        mod = _mod()
        apply_settings_update = mod.apply_settings_update

        data = MagicMock()
        data.model_fields_set = {"log_level"}
        data.log_level = "WARNING"

        db = AsyncMock()
        db.commit = AsyncMock()

        with (
            patch("spectra_api.services.system.settings_service.upsert_system_config_values") as mock_upsert,
            patch("spectra_api.services.system.settings_service.hydrate_runtime_settings_from_db") as mock_hydrate,
            patch("spectra_api.services.system.settings_service.settings") as mock_settings,
        ):
            mock_settings.save_runtime_settings = MagicMock()
            result = await apply_settings_update(data, db)

        assert result["status"] == "updated"
        mock_upsert.assert_awaited_once()
        db.commit.assert_awaited()
        mock_hydrate.assert_awaited_once()


class TestGetCurrentSettings:
    """Tests for get_current_settings()."""

    def test_includes_expected_computed_fields(self):
        mod = _mod()
        settings_stub = SimpleNamespace(
            TENSORZERO_GATEWAY_URL="http://tensorzero:3000",
            TENSORZERO_API_KEY="configured",
            LLM_TIMEOUT=600,
            MAINTENANCE_MODE=False,
            MAINTENANCE_MESSAGE="",
            LOG_LEVEL="INFO",
            CONNECT_BACK_HOST="teamserver.local",
            REQUIRE_APPROVAL=False,
            NOTIFICATION_WEBHOOK=None,
            PLATFORM_DOMAIN="spectra.local",
            PLATFORM_BASE_URL="https://spectra.local",
            PLATFORM_EXPOSED=True,
            PAYMENT_PROVIDER="stripe",
            STRIPE_PUBLISHABLE_KEY="pk_test_123",
            STRIPE_SECRET_KEY="sk_test_123",
            STRIPE_WEBHOOK_SECRET="whsec_123",
            CRYPTO_PAYMENT_URL="",
            CRYPTO_PAYMENT_API_KEY="",
            SANDBOX_MAX_CONTAINERS=10,
            SANDBOX_MEMORY_LIMIT="2g",
            SANDBOX_CPU_SHARES=512,
            SANDBOX_MAX_LIFETIME=7200,
            SANDBOX_RESOURCE_TIERS='{"default": {}}',
            SANDBOX_NETWORK_ISOLATION=True,
            SANDBOX_IDLE_TIMEOUT=600,
            SANDBOX_HEARTBEAT_INTERVAL=30,
            SANDBOX_PER_USER_LIMIT=3,
            SANDBOX_DEFAULT_PRIORITY=5,
            SANDBOX_OOM_ESCALATION_ENABLED=True,
            SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL=False,
            SANDBOX_ORCHESTRATOR_URL="http://sandbox-orchestrator",
            SANDBOX_ORCHESTRATOR_TIMEOUT=15,
            S3_ENDPOINT_URL="",
            S3_REGION="us-east-1",
            EMBEDDING_MODEL="all-MiniLM-L6-v2",
            EMBEDDING_API_BASE_URL=None,
        )

        with (
            patch.object(mod, "settings", settings_stub),
            patch.object(mod, "get_sandbox_status", return_value={"available": True, "message": "Docker connected"}),
        ):
            result = mod.get_current_settings()

        assert result["tensorzero_api_key_configured"] is True
        assert result["notification_webhook"] == ""
        assert result["sandbox_available"] == {"available": True, "message": "Docker connected"}
        assert result["s3_configured"] is False
        assert result["embedding_api_base_url"] is None
        assert result["payment_provider"] == "stripe"
        assert result["stripe_publishable_key"] == "pk_test_123"
        assert result["stripe_secret_key_configured"] is True
        assert result["stripe_webhook_secret_configured"] is True
