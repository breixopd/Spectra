"""Tests for app/services/system/settings_service.py.

Uses sys.modules pre-population to break the circular import chain
(settings_service → schemas → api.__init__ → routers → ui → settings_service).
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _break_circular_import():
    """Pre-populate heavy modules so the import chain doesn't recurse."""
    stubs = {}
    for mod_name in (
        "app.api",
        "app.api.schemas",
        "app.api.routers",
        "app.api.routers.ui",
    ):
        if mod_name not in sys.modules:
            stubs[mod_name] = sys.modules.setdefault(mod_name, MagicMock())
    yield
    for mod_name, stub in stubs.items():
        if sys.modules.get(mod_name) is stub:
            del sys.modules[mod_name]


def _mod():
    from app.services.system import settings_service
    return settings_service


class TestPublicAiProvider:
    """Tests for public_ai_provider()."""

    def _fn(self):
        return _mod().public_ai_provider

    def test_none_defaults_to_litellm(self):
        assert self._fn()(None) == "litellm"

    def test_empty_defaults_to_litellm(self):
        assert self._fn()("") == "litellm"

    def test_ollama(self):
        assert self._fn()("ollama") == "ollama"

    def test_ollama_case_insensitive(self):
        fn = self._fn()
        assert fn("Ollama") == "ollama"
        assert fn("OLLAMA") == "ollama"

    def test_litellm_passthrough(self):
        assert self._fn()("litellm") == "litellm"

    def test_api_becomes_litellm(self):
        assert self._fn()("api") == "litellm"

    def test_whitespace_stripped(self):
        assert self._fn()("  ollama  ") == "ollama"


class TestGetSandboxStatus:
    """Tests for get_sandbox_status()."""

    def _fn(self):
        return _mod().get_sandbox_status

    def test_pool_available(self):
        pool = MagicMock()
        pool.available = True
        with patch(
            "app.services.tools.sandbox.get_sandbox_pool",
            return_value=pool,
        ):
            status = self._fn()()
        assert status["available"] is True

    def test_pool_unavailable(self):
        pool = MagicMock()
        pool.available = False
        with patch(
            "app.services.tools.sandbox.get_sandbox_pool",
            return_value=pool,
        ):
            status = self._fn()()
        assert status["available"] is False

    def test_pool_none(self):
        with patch(
            "app.services.tools.sandbox.get_sandbox_pool",
            return_value=None,
        ):
            status = self._fn()()
        assert status["available"] is False

    def test_exception_returns_unavailable(self):
        with patch(
            "app.services.tools.sandbox.get_sandbox_pool",
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

    def test_maps_bool_field(self):
        data = self._make_data(fully_automated=True)
        result = self._fn()(data, {"fully_automated"})
        assert result["FULLY_AUTOMATED"] == ("true", False)

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


class TestApplySettingsUpdate:
    """Tests for apply_settings_update async function."""

    @pytest.mark.asyncio
    async def test_persists_and_commits(self):
        mod = _mod()
        apply_settings_update = mod.apply_settings_update
        ai_fields = mod._AI_FIELD_NAMES

        data = MagicMock()
        data.model_fields_set = {"log_level"}
        data.log_level = "WARNING"
        for f in ai_fields:
            setattr(data, f, None)

        db = AsyncMock()
        db.commit = AsyncMock()

        with patch("app.services.system.settings_service.upsert_system_config_values") as mock_upsert, \
             patch("app.services.system.settings_service.hydrate_runtime_settings_from_db") as mock_hydrate, \
             patch("app.services.system.settings_service.settings") as mock_settings:
            mock_settings.save_runtime_settings = MagicMock()
            result = await apply_settings_update(data, db)

        assert result["status"] == "updated"
        mock_upsert.assert_awaited_once()
        db.commit.assert_awaited()
        mock_hydrate.assert_awaited_once()


class TestAiFieldNames:
    """Verify the AI field-name frozenset contains expected fields."""

    def _fields(self):
        return _mod()._AI_FIELD_NAMES

    def test_contains_core_fields(self):
        fields = self._fields()
        assert "ai_provider" in fields
        assert "llm_api_key" in fields
        assert "llm_model" in fields

    def test_does_not_contain_general_fields(self):
        fields = self._fields()
        assert "log_level" not in fields
        assert "fully_automated" not in fields
