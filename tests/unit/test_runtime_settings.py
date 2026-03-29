from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from app.services.system.runtime_settings import (
    GENERAL_RUNTIME_FIELD_MAP,
    _apply_general_runtime_settings,
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
async def test_hydrate_runtime_settings_applies_rows_and_resets_caches():
    session = AsyncMock()
    rows = [
        SimpleNamespace(key="TENSORZERO_GATEWAY_URL", value="http://tensorzero:3000"),
        SimpleNamespace(key="EMBEDDING_MODEL", value="text-embedding-3-small"),
        SimpleNamespace(key="SANDBOX_MAX_CONTAINERS", value="5"),
    ]
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session.execute.return_value = result

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

    import contextlib

    with contextlib.ExitStack() as stack:
        stack.enter_context(patch("app.core.lifespan.CacheService", return_value=MagicMock()))
        stack.enter_context(patch("app.core.lifespan.set_cache"))
        stack.enter_context(patch("app.core.lifespan.set_system_status", new_callable=AsyncMock))
        stack.enter_context(patch("app.core.lifespan.add_system_operation", new_callable=AsyncMock))
        stack.enter_context(patch("app.core.lifespan.remove_system_operation", new_callable=AsyncMock))
        stack.enter_context(patch("app.core.lifespan.telemetry.update_service_status"))
        mock_init_registry = stack.enter_context(
            patch("app.services.tools.registry.initialize_registry", new_callable=AsyncMock)
        )
        stack.enter_context(patch("app.core.lifespan.events.emit", new_callable=AsyncMock))
        stack.enter_context(patch("app.core.lifespan.run_startup_tasks"))
        stack.enter_context(patch("app.core.lifespan.close_global_llm_client", new_callable=AsyncMock))
        stack.enter_context(patch("app.core.lifespan.engine", new=MagicMock(dispose=AsyncMock())))
        stack.enter_context(patch("app.core.lifespan.asyncio.all_tasks", return_value=[task]))
        stack.enter_context(patch("app.core.lifespan.asyncio.gather", new_callable=AsyncMock))
        stack.enter_context(patch("app.core.lifespan.asyncio.wait_for", new_callable=AsyncMock))
        stack.enter_context(patch("app.core.lifespan.asyncio.create_task", return_value=task))
        mock_hydrate = stack.enter_context(
            patch("app.core.lifespan.hydrate_runtime_settings_from_db", new_callable=AsyncMock)
        )
        stack.enter_context(patch("app.services.ai.embeddings.EmbeddingService", FakeEmbeddingService))
        stack.enter_context(patch("app.core.bridge.EventWebSocketBridge", return_value=FakeBridge()))
        stack.enter_context(patch("app.core.lifespan.run_startup_checks", new_callable=AsyncMock))
        stack.enter_context(patch("app.core.lifespan._validate_production_secrets"))
        stack.enter_context(patch("app.core.lifespan.seed_default_plans", new_callable=AsyncMock))
        stack.enter_context(
            patch("app.core.metrics_store.get_metrics_store", return_value=MagicMock(start=AsyncMock()))
        )
        stack.enter_context(patch("app.services.storage.get_storage_service", return_value=MagicMock(is_s3=True, health_check=AsyncMock(return_value={"status": "healthy", "endpoint": "http://minio:9000"}))))
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

        from app.core.lifespan import lifespan

        mock_init_registry.return_value = MagicMock(list_tools=MagicMock(return_value=[]))
        mock_hydrate.side_effect = lambda *args, **kwargs: order.append("hydrate")

        async with lifespan(app):
            pass

    assert order[:2] == ["hydrate", "embedding-init"]


def test_sandbox_settings_in_general_runtime_field_map():
    assert "SANDBOX_MAX_CONTAINERS" in GENERAL_RUNTIME_FIELD_MAP
    assert "SANDBOX_MEMORY_LIMIT" in GENERAL_RUNTIME_FIELD_MAP
    assert "SANDBOX_CPU_SHARES" in GENERAL_RUNTIME_FIELD_MAP
    assert "SANDBOX_MAX_LIFETIME" in GENERAL_RUNTIME_FIELD_MAP
    assert GENERAL_RUNTIME_FIELD_MAP["SANDBOX_MAX_CONTAINERS"][1] == "int"
    assert GENERAL_RUNTIME_FIELD_MAP["SANDBOX_MEMORY_LIMIT"][1] == "str"
    assert GENERAL_RUNTIME_FIELD_MAP["SANDBOX_CPU_SHARES"][1] == "int"
    assert GENERAL_RUNTIME_FIELD_MAP["SANDBOX_MAX_LIFETIME"][1] == "int"


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
            "SANDBOX_WARM_POOL_ENABLED",
            "SANDBOX_WARM_POOL_SIZE",
            "SANDBOX_AUTO_BUILD_IMAGE",
            "SANDBOX_IMAGE_SCAN_ENABLED",
            "SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL",
        ]
        for key in new_keys:
            assert key in GENERAL_RUNTIME_FIELD_MAP, f"Missing key: {key}"

    def test_field_map_types_correct(self):
        type_checks = {
            "SANDBOX_NETWORK_ISOLATION": "bool",
            "SANDBOX_OOM_ESCALATION_ENABLED": "bool",
            "SANDBOX_WARM_POOL_ENABLED": "bool",
            "SANDBOX_AUTO_BUILD_IMAGE": "bool",
            "SANDBOX_IMAGE_SCAN_ENABLED": "bool",
            "SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL": "bool",
            "SANDBOX_IDLE_TIMEOUT": "int",
            "SANDBOX_HEARTBEAT_INTERVAL": "int",
            "SANDBOX_PER_USER_LIMIT": "int",
            "SANDBOX_DEFAULT_PRIORITY": "int",
            "SANDBOX_WARM_POOL_SIZE": "int",
            "SANDBOX_RESOURCE_TIERS": "str",
        }
        for key, expected_type in type_checks.items():
            _, actual_type = GENERAL_RUNTIME_FIELD_MAP[key]
            assert actual_type == expected_type, f"{key}: expected {expected_type}, got {actual_type}"
