from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from app.services.system.runtime_settings import (
    apply_runtime_settings,
    hydrate_runtime_settings_from_db,
    normalize_runtime_ai_config,
)


def test_normalize_runtime_ai_config_from_legacy_rows():
    rows = {
        "AI_PROVIDER": "api",
        "LLM_MODEL": "gpt-4o-mini",
        "LLM_API_KEY": "sk-test",
        "LLM_API_BASE_URL": "https://example.test/v1",
        "LLM_TIER1_MODEL": "ollama/qwen2.5:3b",
        "LLM_TIER2_MODEL": "gpt-4o-mini",
        "OLLAMA_ENABLED": "true",
        "OLLAMA_HOST": "http://ollama:11434",
        "OLLAMA_MODEL": "qwen2.5:7b",
    }

    runtime_ai_config = normalize_runtime_ai_config(rows)

    assert runtime_ai_config.routing == {
        "default": "default",
        "tier1": "tier1",
        "tier2": "tier2",
    }
    assert runtime_ai_config.profiles["default"]["provider"] == "litellm"
    assert runtime_ai_config.profiles["default"]["model"] == "gpt-4o-mini"
    assert runtime_ai_config.profiles["ollama"]["provider"] == "litellm"
    assert runtime_ai_config.profiles["ollama"]["model"] == "ollama/qwen2.5:7b"
    assert runtime_ai_config.profiles["tier1"]["provider"] == "litellm"
    assert runtime_ai_config.profiles["tier1"]["model"] == "ollama/qwen2.5:3b"
    assert runtime_ai_config.fallbacks == {"default": ["ollama"]}


def test_normalize_runtime_ai_config_normalizes_structured_api_profiles():
    rows = {
        "AI_PROVIDER": "api",
        "AI_PROVIDER_PROFILES": (
            '{"default": {"provider": "api", "model": "gpt-4o-mini", '
            '"base_url": "https://example.test/v1", "api_key": "sk-test"}}'
        ),
        "AI_PROVIDER_ROUTING": '{"default": "default"}',
    }

    runtime_ai_config = normalize_runtime_ai_config(rows)

    assert runtime_ai_config.profiles["default"]["provider"] == "litellm"
    assert runtime_ai_config.profiles["default"]["model"] == "gpt-4o-mini"
    assert runtime_ai_config.profiles["default"]["base_url"] == "https://example.test/v1"


@pytest.mark.asyncio
async def test_hydrate_runtime_settings_invalidates_ai_caches():
    session = AsyncMock()
    rows = [
        SimpleNamespace(key="AI_PROVIDER", value="api"),
        SimpleNamespace(key="LLM_MODEL", value="gpt-4o-mini"),
        SimpleNamespace(key="LLM_API_KEY", value="sk-test"),
        SimpleNamespace(key="OLLAMA_ENABLED", value="false"),
    ]
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session.execute.return_value = result

    with (
        patch(
            "app.services.system.runtime_settings._persist_normalized_runtime_ai_config",
            new_callable=AsyncMock,
        ) as mock_persist,
        patch(
            "app.services.system.runtime_settings.reset_runtime_ai_caches",
            new_callable=AsyncMock,
        ) as mock_reset,
    ):
        runtime_ai_config = await hydrate_runtime_settings_from_db(
            session,
            persist_normalized=True,
            commit=False,
            reset_caches=True,
        )

    assert runtime_ai_config.routing["default"] == "default"
    mock_persist.assert_awaited_once()
    mock_reset.assert_awaited_once_with()


def test_apply_runtime_settings_sets_resolved_fields():
    rows = {
        "AI_PROVIDER": "ollama",
        "OLLAMA_HOST": "http://ollama:11434",
        "OLLAMA_MODEL": "qwen2.5:7b",
        "EMBEDDING_PROVIDER": "api",
        "EMBEDDING_MODEL": "text-embedding-3-small",
    }
    runtime_ai_config = normalize_runtime_ai_config(rows)

    with patch("app.services.system.runtime_settings.settings") as mock_settings:
        mock_settings.OLLAMA_HOST = "http://default"
        mock_settings.OLLAMA_MODEL = "fallback"
        mock_settings.LLM_MODEL = "fallback-model"
        apply_runtime_settings(rows, runtime_ai_config)

    assert mock_settings.AI_PROVIDER == "litellm"
    assert mock_settings.AI_PROVIDER_ROUTING == {"default": "default"}
    assert mock_settings.OLLAMA_MODEL == "qwen2.5:7b"
    assert mock_settings.EMBEDDING_PROVIDER == "api"
    assert mock_settings.EMBEDDING_MODEL == "text-embedding-3-small"


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

    with (
        patch("app.core.lifespan.CacheService", return_value=MagicMock()),
        patch("app.core.lifespan.set_cache"),
        patch("app.core.lifespan.set_system_status", new_callable=AsyncMock),
        patch("app.core.lifespan.add_system_operation", new_callable=AsyncMock),
        patch("app.core.lifespan.remove_system_operation", new_callable=AsyncMock),
        patch("app.core.lifespan.telemetry.update_service_status"),
        patch("app.services.tools.registry.initialize_registry", new_callable=AsyncMock) as mock_init_registry,
        patch("app.core.lifespan.events.emit", new_callable=AsyncMock),
        patch("app.core.lifespan.run_startup_tasks"),
        patch("app.core.lifespan.close_global_llm_client", new_callable=AsyncMock),
        patch("app.core.lifespan.engine", new=MagicMock(dispose=AsyncMock())),
        patch("app.core.lifespan.asyncio.all_tasks", return_value=[task]),
        patch("app.core.lifespan.asyncio.gather", new_callable=AsyncMock),
        patch("app.core.lifespan.asyncio.wait_for", new_callable=AsyncMock),
        patch("app.core.lifespan.asyncio.create_task", return_value=task),
        patch("app.core.lifespan.hydrate_runtime_settings_from_db", new_callable=AsyncMock) as mock_hydrate,
        patch("app.services.ai.embeddings.EmbeddingService", FakeEmbeddingService),
        patch("app.core.bridge.EventWebSocketBridge", return_value=FakeBridge()),
    ):
        from app.core.lifespan import lifespan

        mock_init_registry.return_value = MagicMock(list_tools=MagicMock(return_value=[]))
        mock_hydrate.side_effect = lambda *args, **kwargs: order.append("hydrate")

        async with lifespan(app):
            pass

    assert order[:2] == ["hydrate", "embedding-init"]
