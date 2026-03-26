import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_current_active_user
from app.api.routers import ui
from app.core.database import get_async_session
from app.services.system import settings_service as _svc


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
        REQUIRE_APPROVAL=False,
        FULLY_AUTOMATED=True,
        NOTIFICATION_WEBHOOK="",
        LLM_TIER1_MODEL="ollama/qwen2.5:3b",
        LLM_TIER2_MODEL="",
        LLM_TIER3_MODEL="",
        EMBEDDING_MODEL="all-MiniLM-L6-v2",
        EMBEDDING_API_KEY=SimpleNamespace(get_secret_value=lambda: ""),
        EMBEDDING_API_BASE_URL="",
        PLATFORM_DOMAIN="",
        PLATFORM_BASE_URL="",
        PLATFORM_EXPOSED=False,
        SANDBOX_MAX_CONTAINERS=10,
        SANDBOX_MEMORY_LIMIT="2g",
        SANDBOX_CPU_SHARES=512,
        SANDBOX_MAX_LIFETIME=7200,
        SANDBOX_RESOURCE_TIERS='{"light": {"memory": "512m", "cpu_shares": 256}, "medium": {"memory": "2g", "cpu_shares": 512}, "heavy": {"memory": "4g", "cpu_shares": 1024}, "extreme": {"memory": "8g", "cpu_shares": 2048}}',
        SANDBOX_NETWORK_ISOLATION=True,
        SANDBOX_IDLE_TIMEOUT=600,
        SANDBOX_HEARTBEAT_INTERVAL=30,
        SANDBOX_PER_USER_LIMIT=3,
        SANDBOX_DEFAULT_PRIORITY=5,
        SANDBOX_OOM_ESCALATION_ENABLED=True,
        SANDBOX_WARM_POOL_ENABLED=False,
        SANDBOX_WARM_POOL_SIZE=2,
        SANDBOX_AUTO_BUILD_IMAGE=False,
        SANDBOX_IMAGE_SCAN_ENABLED=False,
        SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL=False,
        SANDBOX_ORCHESTRATOR_URL=None,
        SANDBOX_ORCHESTRATOR_TIMEOUT=30,
        S3_ENDPOINT_URL="",
        S3_REGION="us-east-1",
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
        patch.object(_svc, "settings", settings_stub),
        patch.object(_svc, "upsert_system_config_values", mock_upsert),
        patch.object(_svc, "hydrate_runtime_settings_from_db", mock_hydrate),
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
                    "provider_fallbacks": {"default": ["tier1", "tier2"]},
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
    assert profiles["tier2"]["provider"] == "tensorzero"
    assert profiles["tier2"]["model"] == "ollama/qwen2.5:14b"
    assert routing == {"default": "default", "tier1": "tier1"}
    assert fallbacks == {"default": ["tier1", "tier2"]}
    mock_hydrate.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_settings_returns_resolved_db_backed_configuration(test_app):
    settings_stub = _make_settings_stub()

    with patch.object(_svc, "settings", settings_stub):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/settings")

    assert response.status_code == 200
    data = response.json()

    assert data["ai_provider"] == "tensorzero"
    assert data["provider_profiles"]["default"]["provider"] == "tensorzero"
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
        patch.object(_svc, "settings", settings_stub),
        patch.object(_svc, "upsert_system_config_values", mock_upsert),
        patch.object(_svc, "hydrate_runtime_settings_from_db", mock_hydrate),
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
        patch.object(_svc, "settings", settings_stub),
        patch("app.services.ai.llm.get_global_llm_client", AsyncMock(return_value=mock_client)),
    ):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/ai/status")

    assert response.status_code == 200
    data = response.json()

    assert data["provider"] == "tensorzero"
    assert data["healthy"] is True
    assert data["default_profile"] == "default"
    assert data["resolved_routing"]["tier1"]["profile"] == "tier1"
    assert data["fallbacks"]["default"] == ["tier1"]
    assert "tensorzero" in data["provider_info"]
    assert "api" not in data["provider_info"]


def test_settings_update_request_normalizes_legacy_api_provider_to_tensorzero():
    payload = ui.SettingsUpdate(ai_provider="api")

    assert payload.ai_provider == "tensorzero"


def test_llm_test_request_normalizes_legacy_api_provider_to_tensorzero():
    payload = ui.LLMTestRequest(provider="api", model="gpt-4o-mini")

    assert payload.provider == "tensorzero"


@pytest.mark.asyncio
async def test_get_settings_includes_sandbox_fields(test_app):
    settings_stub = _make_settings_stub()

    with (
        patch.object(_svc, "settings", settings_stub),
        patch("app.services.ai.router.PROVIDER_PRESETS", {}),
    ):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/settings")

    assert response.status_code == 200
    data = response.json()
    assert data["sandbox_max_containers"] == 10
    assert data["sandbox_memory_limit"] == "2g"
    assert data["sandbox_cpu_shares"] == 512
    assert data["sandbox_max_lifetime"] == 7200
    assert "sandbox_available" in data


@pytest.mark.asyncio
async def test_update_settings_saves_sandbox_fields(test_app):
    settings_stub = _make_settings_stub()
    mock_upsert = AsyncMock()
    mock_hydrate = AsyncMock()

    with (
        patch.object(_svc, "settings", settings_stub),
        patch.object(_svc, "upsert_system_config_values", mock_upsert),
        patch.object(_svc, "hydrate_runtime_settings_from_db", mock_hydrate),
    ):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/settings",
                json={
                    "sandbox_max_containers": 15,
                    "sandbox_memory_limit": "4g",
                    "sandbox_cpu_shares": 1024,
                    "sandbox_max_lifetime": 3600,
                },
            )

    assert response.status_code == 200
    assert mock_upsert.called
    call_args = mock_upsert.call_args[0][1]
    assert "SANDBOX_MAX_CONTAINERS" in call_args
    assert call_args["SANDBOX_MAX_CONTAINERS"] == ("15", False)
    assert call_args["SANDBOX_MEMORY_LIMIT"] == ("4g", False)
    assert call_args["SANDBOX_CPU_SHARES"] == ("1024", False)
    assert call_args["SANDBOX_MAX_LIFETIME"] == ("3600", False)


@pytest.mark.asyncio
async def test_get_settings_returns_new_sandbox_fields(test_app):
    """GET /api/settings returns all 12 new sandbox fields."""
    settings_stub = _make_settings_stub()
    with patch.object(_svc, "settings", settings_stub):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["sandbox_network_isolation"] is True
    assert data["sandbox_idle_timeout"] == 600
    assert data["sandbox_heartbeat_interval"] == 30
    assert data["sandbox_per_user_limit"] == 3
    assert data["sandbox_default_priority"] == 5
    assert data["sandbox_oom_escalation_enabled"] is True
    assert data["sandbox_warm_pool_enabled"] is False
    assert data["sandbox_warm_pool_size"] == 2
    assert data["sandbox_auto_build_image"] is False
    assert data["sandbox_image_scan_enabled"] is False
    assert data["sandbox_image_scan_block_critical"] is False
    assert "sandbox_resource_tiers" in data


@pytest.mark.asyncio
async def test_update_new_sandbox_settings_persists(test_app):
    """POST /api/settings with new sandbox fields persists to DB."""
    settings_stub = _make_settings_stub()
    mock_upsert = AsyncMock()
    mock_hydrate = AsyncMock()

    with (
        patch.object(_svc, "settings", settings_stub),
        patch.object(_svc, "upsert_system_config_values", mock_upsert),
        patch.object(_svc, "hydrate_runtime_settings_from_db", mock_hydrate),
    ):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/settings",
                json={
                    "sandbox_network_isolation": False,
                    "sandbox_idle_timeout": 300,
                    "sandbox_warm_pool_enabled": True,
                    "sandbox_warm_pool_size": 5,
                    "sandbox_per_user_limit": 10,
                    "sandbox_default_priority": 2,
                    "sandbox_oom_escalation_enabled": False,
                    "sandbox_auto_build_image": True,
                    "sandbox_image_scan_enabled": True,
                    "sandbox_image_scan_block_critical": True,
                },
            )

    assert response.status_code == 200
    persisted = mock_upsert.await_args.args[1]
    assert persisted["SANDBOX_NETWORK_ISOLATION"] == ("false", False)
    assert persisted["SANDBOX_IDLE_TIMEOUT"] == ("300", False)
    assert persisted["SANDBOX_WARM_POOL_ENABLED"] == ("true", False)
    assert persisted["SANDBOX_WARM_POOL_SIZE"] == ("5", False)
    assert persisted["SANDBOX_PER_USER_LIMIT"] == ("10", False)
    assert persisted["SANDBOX_DEFAULT_PRIORITY"] == ("2", False)
    assert persisted["SANDBOX_OOM_ESCALATION_ENABLED"] == ("false", False)
    assert persisted["SANDBOX_AUTO_BUILD_IMAGE"] == ("true", False)
    assert persisted["SANDBOX_IMAGE_SCAN_ENABLED"] == ("true", False)
    assert persisted["SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL"] == ("true", False)
