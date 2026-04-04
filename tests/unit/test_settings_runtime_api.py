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
        TENSORZERO_GATEWAY_URL="http://tensorzero:3000",
        TENSORZERO_API_KEY="",
        LLM_TIMEOUT=600,
        MAINTENANCE_MODE=False,
        MAINTENANCE_MESSAGE="",
        LOG_LEVEL="INFO",
        PLUGIN_SAFE_MODE=True,
        CONNECT_BACK_HOST="spectra-app",
        REQUIRE_APPROVAL=False,
        FULLY_AUTOMATED=True,
        NOTIFICATION_WEBHOOK="",
        PLATFORM_DOMAIN="",
        PLATFORM_BASE_URL="",
        PLATFORM_EXPOSED=False,
        SANDBOX_MAX_CONTAINERS=10,
        SANDBOX_MEMORY_LIMIT="2g",
        SANDBOX_CPU_SHARES=512,
        SANDBOX_MAX_LIFETIME=7200,
        SANDBOX_RESOURCE_TIERS='{"light": {"memory": "512m", "cpu_shares": 256}}',
        SANDBOX_NETWORK_ISOLATION=True,
        SANDBOX_IDLE_TIMEOUT=600,
        SANDBOX_HEARTBEAT_INTERVAL=30,
        SANDBOX_PER_USER_LIMIT=3,
        SANDBOX_DEFAULT_PRIORITY=5,
        SANDBOX_OOM_ESCALATION_ENABLED=True,
        SANDBOX_WARM_POOL_SIZE=2,
        SANDBOX_AUTO_BUILD_IMAGE=False,
        SANDBOX_IMAGE_SCAN_ENABLED=False,
        SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL=False,
        SANDBOX_ORCHESTRATOR_URL=None,
        SANDBOX_ORCHESTRATOR_TIMEOUT=30,
        S3_ENDPOINT_URL="",
        S3_REGION="us-east-1",
        EMBEDDING_MODEL="all-MiniLM-L6-v2",
        EMBEDDING_API_BASE_URL="",
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
async def test_get_settings_returns_current_settings_snapshot(test_app):
    settings_stub = _make_settings_stub()

    with patch.object(_svc, "settings", settings_stub):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/settings")

    assert response.status_code == 200
    data = response.json()
    assert data["tensorzero_gateway_url"] == "http://tensorzero:3000"
    assert data["llm_timeout"] == 600
    assert data["sandbox_max_containers"] == 10
    assert data["sandbox_memory_limit"] == "2g"
    assert data["embedding_model"] == "all-MiniLM-L6-v2"
    assert "sandbox_available" in data


@pytest.mark.asyncio
async def test_update_settings_saves_sandbox_fields(test_app):
    mock_apply = AsyncMock(return_value={"status": "updated", "message": "Settings updated and saved"})

    with patch("app.api.routers.ui.apply_settings_update", mock_apply):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/settings",
                json={
                    "sandbox_max_containers": 12,
                    "sandbox_memory_limit": "4g",
                    "sandbox_cpu_shares": 1024,
                    "sandbox_max_lifetime": 3600,
                },
            )

    assert response.status_code == 200
    payload = mock_apply.await_args.args[0]
    assert payload.sandbox_max_containers == 12
    assert payload.sandbox_memory_limit == "4g"
    assert payload.sandbox_cpu_shares == 1024
    assert payload.sandbox_max_lifetime == 3600


@pytest.mark.asyncio
async def test_get_settings_includes_sandbox_fields(test_app):
    settings_stub = _make_settings_stub()

    with patch.object(_svc, "settings", settings_stub):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/settings")

    assert response.status_code == 200
    data = response.json()
    assert data["sandbox_max_containers"] == 10
    assert data["sandbox_memory_limit"] == "2g"
    assert data["sandbox_cpu_shares"] == 512
    assert data["sandbox_max_lifetime"] == 7200
    assert data["sandbox_network_isolation"] is True
    assert data["sandbox_idle_timeout"] == 600


@pytest.mark.asyncio
async def test_get_settings_returns_new_sandbox_fields(test_app):
    settings_stub = _make_settings_stub()

    with patch.object(_svc, "settings", settings_stub):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/settings")

    assert response.status_code == 200
    data = response.json()
    assert (
        data["sandbox_resource_tiers"] == json.loads(settings_stub.SANDBOX_RESOURCE_TIERS)
        if isinstance(data["sandbox_resource_tiers"], dict)
        else settings_stub.SANDBOX_RESOURCE_TIERS
    )
    assert data["sandbox_per_user_limit"] == 3
    assert data["sandbox_default_priority"] == 5
    assert data["sandbox_oom_escalation_enabled"] is True
    assert data["sandbox_warm_pool_size"] == 2
    assert data["sandbox_auto_build_image"] is False
    assert data["sandbox_image_scan_enabled"] is False
    assert data["sandbox_image_scan_block_critical"] is False


@pytest.mark.asyncio
async def test_ai_status_exposes_current_gateway_snapshot(test_app):
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
    assert data["gateway_url"] == "http://tensorzero:3000"
    assert data["healthy"] is True
    assert data["embedding_model"] == "all-MiniLM-L6-v2"
    assert data["timeout"] == 600
