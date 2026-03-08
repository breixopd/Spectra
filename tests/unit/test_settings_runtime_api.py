import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_current_active_user
from app.api.routers import ui
from app.core.database import get_async_session


def _make_settings_stub() -> SimpleNamespace:
    return SimpleNamespace(
        AI_PROVIDER="api",
        AI_PROVIDER_PROFILES={
            "default": {
                "provider": "api",
                "model": "gpt-4o-mini",
                "base_url": "https://example.test/v1",
                "api_key": "sk-primary",
            },
            "tier1": {
                "provider": "ollama",
                "model": "qwen2.5:3b",
                "base_url": "http://ollama:11434",
            },
        },
        AI_PROVIDER_ROUTING={
            "default": "default",
            "tier1": "tier1",
        },
        AI_PROVIDER_FALLBACKS={
            "default": ["tier1"],
        },
        LLM_MODEL="gpt-4o-mini",
        LLM_API_BASE_URL="https://example.test/v1",
        LLM_API_KEY=SimpleNamespace(get_secret_value=lambda: "sk-primary"),
        OLLAMA_HOST="http://ollama:11434",
        OLLAMA_MODEL="qwen2.5:3b",
        OLLAMA_ENABLED=True,
        LOG_LEVEL="INFO",
        PLUGIN_SAFE_MODE=True,
        CONNECT_BACK_HOST="spectra-app",
        TOOL_CONTAINER_NAME="spectra-tools",
        REQUIRE_APPROVAL=False,
        FULLY_AUTOMATED=True,
        NOTIFICATION_WEBHOOK="",
        LLM_TIER1_MODEL="ollama/qwen2.5:3b",
        LLM_TIER2_MODEL="",
        LLM_TIER3_MODEL="",
        EMBEDDING_PROVIDER="local",
        EMBEDDING_MODEL="all-MiniLM-L6-v2",
        PLATFORM_DOMAIN="",
        PLATFORM_BASE_URL="",
        PLATFORM_EXPOSED=False,
        save_runtime_settings=MagicMock(),
    )


@pytest.fixture
def test_app():
    app = FastAPI()
    app.include_router(ui.router)

    async def override_user():
        return SimpleNamespace(username="admin", is_active=True, is_superuser=True, role="admin")

    async def override_db():
        return AsyncMock()

    app.dependency_overrides[get_current_active_user] = override_user
    app.dependency_overrides[get_async_session] = override_db
    return app


@pytest.mark.asyncio
async def test_update_settings_merges_partial_runtime_ai_payload(test_app):
    settings_stub = _make_settings_stub()
    mock_upsert = AsyncMock()
    mock_hydrate = AsyncMock()

    with (
        patch.object(ui, "settings", settings_stub),
        patch.object(ui, "upsert_system_config_values", mock_upsert),
        patch.object(ui, "hydrate_runtime_settings_from_db", mock_hydrate),
    ):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/settings",
                json={
                    "provider_profiles": {
                        "tier2": {
                            "provider": "ollama",
                            "model": "qwen2.5:14b",
                            "base_url": "http://ollama:11434",
                        }
                    },
                    "provider_fallbacks": {
                        "default": ["tier1", "tier2"]
                    },
                },
            )

    assert response.status_code == 200
    await_call = mock_upsert.await_args
    assert await_call is not None
    persisted = await_call.args[1]
    profiles = json.loads(persisted["AI_PROVIDER_PROFILES"][0])
    routing = json.loads(persisted["AI_PROVIDER_ROUTING"][0])
    fallbacks = json.loads(persisted["AI_PROVIDER_FALLBACKS"][0])

    assert set(profiles) == {"default", "tier1", "tier2"}
    assert profiles["tier2"]["provider"] == "litellm"
    assert profiles["tier2"]["model"] == "ollama/qwen2.5:14b"
    assert routing == {"default": "default", "tier1": "tier1"}
    assert fallbacks == {"default": ["tier1", "tier2"]}
    mock_hydrate.assert_awaited_once()
    settings_stub.save_runtime_settings.assert_called_once()


@pytest.mark.asyncio
async def test_get_settings_returns_resolved_db_backed_configuration(test_app):
    settings_stub = _make_settings_stub()

    with patch.object(ui, "settings", settings_stub):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/settings")

    assert response.status_code == 200
    data = response.json()

    assert data["ai_provider"] == "litellm"
    assert data["provider_profiles"]["default"]["provider"] == "litellm"
    assert data["provider_routing"]["tier1"] == "tier1"
    assert data["provider_fallbacks"]["default"] == ["tier1"]
    assert data["resolved_ai"]["default_profile"] == "default"
    assert data["resolved_ai"]["tiers"]["tier1"]["profile"] == "tier1"


@pytest.mark.asyncio
async def test_update_settings_can_clear_default_fallback_chain(test_app):
    settings_stub = _make_settings_stub()
    mock_upsert = AsyncMock()
    mock_hydrate = AsyncMock()

    with (
        patch.object(ui, "settings", settings_stub),
        patch.object(ui, "upsert_system_config_values", mock_upsert),
        patch.object(ui, "hydrate_runtime_settings_from_db", mock_hydrate),
    ):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/settings",
                json={
                    "provider_fallbacks": {"default": []},
                },
            )

    assert response.status_code == 200
    await_call = mock_upsert.await_args
    assert await_call is not None
    persisted = await_call.args[1]
    fallbacks = json.loads(persisted["AI_PROVIDER_FALLBACKS"][0])

    assert fallbacks == {}
    mock_hydrate.assert_awaited_once()


@pytest.mark.asyncio
async def test_ai_status_exposes_resolved_runtime_routes(test_app):
    settings_stub = _make_settings_stub()
    mock_client = SimpleNamespace(health_check=AsyncMock(return_value=True))

    with (
        patch.object(ui, "settings", settings_stub),
        patch("app.services.ai.llm.get_global_llm_client", AsyncMock(return_value=mock_client)),
    ):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/ai/status")

    assert response.status_code == 200
    data = response.json()

    assert data["provider"] == "litellm"
    assert data["healthy"] is True
    assert data["default_profile"] == "default"
    assert data["resolved_routing"]["tier1"]["profile"] == "tier1"
    assert data["fallbacks"]["default"] == ["tier1"]
    assert "litellm" in data["provider_info"]
    assert "api" not in data["provider_info"]


def test_settings_update_request_normalizes_legacy_api_provider_to_litellm():
    payload = ui.SettingsUpdateRequest(ai_provider="api")

    assert payload.ai_provider == "litellm"


def test_llm_test_request_normalizes_legacy_api_provider_to_litellm():
    payload = ui.LLMTestRequest(provider="api", model="gpt-4o-mini")

    assert payload.provider == "litellm"