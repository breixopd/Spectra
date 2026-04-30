import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from app.services.system.runtime_settings import (
    BOOTSTRAP_ONLY_VARS,
    GENERAL_RUNTIME_FIELD_MAP,
    _apply_general_runtime_settings,
    _is_explicitly_set_env,
    hydrate_runtime_settings_from_db,
)


def test_apply_general_runtime_settings_sets_expected_fields():
    rows = {
        "TENSORZERO_GATEWAY_URL": "http://tensorzero:3000",
        "EMBEDDING_MODEL": "text-embedding-3-small",
        "PLATFORM_EXPOSED": "true",
        "SANDBOX_MAX_CONTAINERS": "8",
        "NOTIFICATION_WEBHOOK": "https://example.test/hook",
    }

    with patch("app.services.system.runtime_settings.settings") as mock_settings:
        _apply_general_runtime_settings(rows)

    assert mock_settings.TENSORZERO_GATEWAY_URL == "http://tensorzero:3000"
    assert mock_settings.EMBEDDING_MODEL == "text-embedding-3-small"
    assert mock_settings.PLATFORM_EXPOSED is True
    assert mock_settings.SANDBOX_MAX_CONTAINERS == 8
    assert mock_settings.NOTIFICATION_WEBHOOK == "https://example.test/hook"


def test_apply_general_runtime_settings_handles_nullable_and_invalid_ints():
    rows = {
        "NOTIFICATION_WEBHOOK": "",
        "SANDBOX_MAX_CONTAINERS": "not-an-int",
    }

    with patch("app.services.system.runtime_settings.settings") as mock_settings:
        mock_settings.SANDBOX_MAX_CONTAINERS = 4
        _apply_general_runtime_settings(rows)

    assert mock_settings.NOTIFICATION_WEBHOOK is None
    assert mock_settings.SANDBOX_MAX_CONTAINERS == 4


@pytest.mark.asyncio
async def test_hydrate_runtime_settings_applies_rows_and_resets_caches(monkeypatch):
    session = AsyncMock()
    rows = [
        SimpleNamespace(key="TENSORZERO_GATEWAY_URL", value="http://tensorzero:3000"),
        SimpleNamespace(key="EMBEDDING_MODEL", value="text-embedding-3-small"),
        SimpleNamespace(key="SANDBOX_MAX_CONTAINERS", value="5"),
    ]
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session.execute.return_value = result
    monkeypatch.delenv("TENSORZERO_GATEWAY_URL", raising=False)
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("SANDBOX_MAX_CONTAINERS", raising=False)

    with (
        patch("app.services.system.runtime_settings.settings") as mock_settings,
        patch(
            "app.services.system.runtime_settings.reset_runtime_ai_caches",
            new_callable=AsyncMock,
        ) as mock_reset,
    ):
        await hydrate_runtime_settings_from_db(
            session,
            persist_normalized=True,
            commit=False,
            reset_caches=True,
        )

    assert mock_settings.TENSORZERO_GATEWAY_URL == "http://tensorzero:3000"
    assert mock_settings.EMBEDDING_MODEL == "text-embedding-3-small"
    assert mock_settings.SANDBOX_MAX_CONTAINERS == 5
    mock_reset.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_hydrate_runtime_settings_commits_when_requested():
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute.return_value = result

    await hydrate_runtime_settings_from_db(
        session,
        persist_normalized=True,
        commit=True,
        reset_caches=False,
    )

    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_hydrates_runtime_before_embedding_init():
    app = FastAPI()
    order: list[str] = []
    task = AsyncMock()
    task.cancel = MagicMock()

    class FakeEmbeddingService:
        def __init__(self):
            order.append("embedding-init")

        async def _load_model(self):
            return None

    class FakeBridge:
        def start(self):
            return None

        def stop(self):
            return None

    class FakeSessionContext:
        async def __aenter__(self):
            return AsyncMock()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    import contextlib

    with contextlib.ExitStack() as stack:
        stack.enter_context(patch("spectra_api.bootstrap.lifespan.CacheService", return_value=MagicMock()))
        stack.enter_context(patch("spectra_api.bootstrap.lifespan.set_cache"))
        stack.enter_context(patch("spectra_api.bootstrap.lifespan.set_system_status", new_callable=AsyncMock))
        stack.enter_context(patch("spectra_api.bootstrap.lifespan.add_system_operation", new_callable=AsyncMock))
        stack.enter_context(patch("spectra_api.bootstrap.lifespan.remove_system_operation", new_callable=AsyncMock))
        stack.enter_context(patch("spectra_api.bootstrap.lifespan.telemetry.update_service_status"))
        mock_init_registry = stack.enter_context(
            patch("app.services.tools.registry.initialize_registry", new_callable=AsyncMock)
        )
        stack.enter_context(patch("spectra_api.bootstrap.lifespan.events.emit", new_callable=AsyncMock))
        stack.enter_context(patch("spectra_api.bootstrap.lifespan.run_startup_tasks"))
        stack.enter_context(patch("spectra_ai.llm.close_global_llm_client", new_callable=AsyncMock))
        stack.enter_context(patch("spectra_api.bootstrap.lifespan.engine", new=MagicMock(dispose=AsyncMock())))
        stack.enter_context(patch("spectra_api.bootstrap.lifespan.asyncio.all_tasks", return_value=[task]))
        stack.enter_context(patch("spectra_api.bootstrap.lifespan.asyncio.gather", new_callable=AsyncMock))
        stack.enter_context(patch("spectra_api.bootstrap.lifespan.asyncio.wait_for", new_callable=AsyncMock))
        stack.enter_context(patch("spectra_api.bootstrap.lifespan.asyncio.create_task", return_value=task))
        stack.enter_context(patch("spectra_api.bootstrap.lifespan.async_session_maker", return_value=FakeSessionContext()))
        mock_hydrate = stack.enter_context(
            patch("spectra_api.bootstrap.lifespan.hydrate_runtime_settings_from_db", new_callable=AsyncMock)
        )
        stack.enter_context(patch("app.services.storage.close_storage_service", new_callable=AsyncMock))
        stack.enter_context(patch("spectra_ai.embeddings.EmbeddingService", FakeEmbeddingService))
        stack.enter_context(patch("app.mission.core.bridge.EventWebSocketBridge", return_value=FakeBridge()))
        stack.enter_context(patch("spectra_api.bootstrap.lifespan.run_startup_checks", new_callable=AsyncMock))
        stack.enter_context(patch("spectra_api.bootstrap.lifespan._validate_rate_limit_storage"))
        stack.enter_context(patch("spectra_api.bootstrap.lifespan.seed_default_plans", new_callable=AsyncMock))
        stack.enter_context(
            patch("app.services.system.secret_bootstrap.ensure_persistent_secrets", new_callable=AsyncMock)
        )
        stack.enter_context(
            patch("app.infrastructure.metrics_store.get_metrics_store", return_value=MagicMock(start=AsyncMock()))
        )
        stack.enter_context(
            patch(
                "app.services.storage.get_storage_service",
                return_value=MagicMock(
                    is_s3=True,
                    start=AsyncMock(),
                    health_check=AsyncMock(return_value={"status": "healthy", "endpoint": "http://garage:3900"}),
                ),
            )
        )
        stack.enter_context(
            patch("app.services.gateway.service_registry.get_service_registry", return_value=MagicMock())
        )
        stack.enter_context(
            patch(
                "app.services.scaling.get_pool_manager",
                return_value=MagicMock(start_health_loop=AsyncMock(), stop_health_loop=AsyncMock()),
            )
        )
        stack.enter_context(
            patch("app.services.tools.sandbox.pool.SandboxPool", return_value=MagicMock(available=False))
        )
        stack.enter_context(patch("app.services.tools.sandbox.SandboxPool", return_value=MagicMock(available=False)))

        mock_settings = stack.enter_context(patch("spectra_api.bootstrap.lifespan.settings"))
        mock_settings.AI_SERVICE_URL = ""
        mock_settings.DEBUG = True
        mock_settings.SERVICE_MODE = "api"
        mock_settings.PAYMENT_PROVIDER = "noop"
        mock_settings.STRIPE_SECRET_KEY = SecretStr("")
        mock_settings.STRIPE_WEBHOOK_SECRET = SecretStr("")

        from spectra_api.bootstrap.lifespan import lifespan

        mock_init_registry.return_value = MagicMock(list_tools=MagicMock(return_value=[]))
        mock_hydrate.side_effect = lambda *args, **kwargs: order.append("hydrate")

        async with lifespan(app):
            pass

    assert order[:2] == ["hydrate", "embedding-init"]


def test_validate_stripe_webhook_secret_raises_when_required(caplog):
    from spectra_api.bootstrap.lifespan import _validate_stripe_webhook_secret

    with patch("spectra_api.bootstrap.lifespan.settings") as mock_settings:
        mock_settings.PAYMENT_PROVIDER = "stripe"
        mock_settings.STRIPE_SECRET_KEY = SecretStr("sk_test_123")
        mock_settings.STRIPE_WEBHOOK_SECRET = SecretStr("")

        with caplog.at_level("ERROR"):
            with pytest.raises(RuntimeError, match="STRIPE_WEBHOOK_SECRET"):
                _validate_stripe_webhook_secret()

    assert "STRIPE_WEBHOOK_SECRET is empty" in caplog.text


def test_validate_stripe_webhook_secret_skips_when_not_actively_using_stripe():
    from spectra_api.bootstrap.lifespan import _validate_stripe_webhook_secret

    with patch("spectra_api.bootstrap.lifespan.settings") as mock_settings:
        mock_settings.PAYMENT_PROVIDER = "manual"
        mock_settings.STRIPE_SECRET_KEY = SecretStr("sk_test_123")
        mock_settings.STRIPE_WEBHOOK_SECRET = SecretStr("")
        _validate_stripe_webhook_secret()

        mock_settings.PAYMENT_PROVIDER = "stripe"
        mock_settings.STRIPE_SECRET_KEY = SecretStr("")
        _validate_stripe_webhook_secret()


def test_sandbox_settings_in_general_runtime_field_map():
    assert "SANDBOX_MAX_CONTAINERS" in GENERAL_RUNTIME_FIELD_MAP
    assert "SANDBOX_MEMORY_LIMIT" in GENERAL_RUNTIME_FIELD_MAP
    assert "SANDBOX_CPU_SHARES" in GENERAL_RUNTIME_FIELD_MAP
    assert "SANDBOX_MAX_LIFETIME" in GENERAL_RUNTIME_FIELD_MAP
    assert GENERAL_RUNTIME_FIELD_MAP["SANDBOX_MAX_CONTAINERS"][1] == "int"
    assert GENERAL_RUNTIME_FIELD_MAP["SANDBOX_MEMORY_LIMIT"][1] == "str"
    assert GENERAL_RUNTIME_FIELD_MAP["SANDBOX_CPU_SHARES"][1] == "int"
    assert GENERAL_RUNTIME_FIELD_MAP["SANDBOX_MAX_LIFETIME"][1] == "int"
    for internal_key in ("SANDBOX_IMAGE", "SANDBOX_NETWORK", "SANDBOX_PLUGINS_VOLUME"):
        assert internal_key not in GENERAL_RUNTIME_FIELD_MAP


class TestGeneralRuntimeFieldMapIncludes:
    def test_field_map_has_new_sandbox_keys(self):
        new_keys = [
            "SANDBOX_RESOURCE_TIERS",
            "SANDBOX_NETWORK_ISOLATION",
            "SANDBOX_IDLE_TIMEOUT",
            "SANDBOX_HEARTBEAT_INTERVAL",
            "SANDBOX_PER_USER_LIMIT",
            "SANDBOX_DEFAULT_PRIORITY",
            "SANDBOX_OOM_ESCALATION_ENABLED",
            "SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL",
        ]
        for key in new_keys:
            assert key in GENERAL_RUNTIME_FIELD_MAP, f"Missing key: {key}"

    def test_field_map_types_correct(self):
        type_checks = {
            "SANDBOX_NETWORK_ISOLATION": "bool",
            "SANDBOX_OOM_ESCALATION_ENABLED": "bool",
            "SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL": "bool",
            "SANDBOX_IDLE_TIMEOUT": "int",
            "SANDBOX_HEARTBEAT_INTERVAL": "int",
            "SANDBOX_PER_USER_LIMIT": "int",
            "SANDBOX_DEFAULT_PRIORITY": "int",
            "SANDBOX_RESOURCE_TIERS": "str",
        }
        for key, expected_type in type_checks.items():
            _, actual_type = GENERAL_RUNTIME_FIELD_MAP[key]
            assert actual_type == expected_type, f"{key}: expected {expected_type}, got {actual_type}"


class TestIsExplicitlySetEnv:
    def test_returns_true_when_env_var_set(self):
        with patch.dict(os.environ, {"MY_TEST_VAR": "hello"}):
            assert _is_explicitly_set_env("MY_TEST_VAR") is True

    def test_returns_false_when_env_var_missing(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MY_TEST_VAR_ABSENT", None)
            assert _is_explicitly_set_env("MY_TEST_VAR_ABSENT") is False

    def test_returns_true_for_empty_string_value(self):
        with patch.dict(os.environ, {"MY_TEST_VAR_EMPTY": ""}):
            assert _is_explicitly_set_env("MY_TEST_VAR_EMPTY") is True


@pytest.mark.asyncio
async def test_hydrate_env_override_takes_precedence_over_db():
    """When an env var is explicitly set, it overrides the DB value."""
    session = AsyncMock()
    rows = [
        SimpleNamespace(key="PLATFORM_DOMAIN", value="from-db.example.com", is_secret=False),
    ]
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session.execute.return_value = result

    with (
        patch("app.services.system.runtime_settings.settings") as mock_settings,
        patch(
            "app.services.system.runtime_settings.reset_runtime_ai_caches",
            new_callable=AsyncMock,
        ),
        patch.dict(os.environ, {"PLATFORM_DOMAIN": "from-env.example.com"}),
    ):
        await hydrate_runtime_settings_from_db(
            session,
            persist_normalized=False,
            commit=False,
            reset_caches=False,
        )

    # Env var should override DB value for non-bootstrap vars
    assert mock_settings.PLATFORM_DOMAIN == "from-env.example.com"


@pytest.mark.asyncio
async def test_hydrate_bootstrap_only_vars_skip_env_override():
    """BOOTSTRAP_ONLY_VARS should NOT be overridden from env during hydration."""
    session = AsyncMock()
    rows = [
        SimpleNamespace(key="DATABASE_URL", value="from-db", is_secret=False),
    ]
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session.execute.return_value = result

    with (
        patch("app.services.system.runtime_settings.settings"),
        patch(
            "app.services.system.runtime_settings.reset_runtime_ai_caches",
            new_callable=AsyncMock,
        ),
        patch.dict(os.environ, {"DATABASE_URL": "from-env"}),
    ):
        await hydrate_runtime_settings_from_db(
            session,
            persist_normalized=False,
            commit=False,
            reset_caches=False,
        )

    # DATABASE_URL is in BOOTSTRAP_ONLY_VARS so should NOT appear in the field map
    assert "DATABASE_URL" in BOOTSTRAP_ONLY_VARS
    assert "DATABASE_URL" not in GENERAL_RUNTIME_FIELD_MAP
