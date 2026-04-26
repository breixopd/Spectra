"""Router-level VPN authorization tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _make_app(role: str):
    from app.api.dependencies import get_current_active_user
    from app.api.routers.vpn import router
    from app.core.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    limiter.enabled = False
    app.include_router(router, prefix="/api/v1")

    user = MagicMock()
    user.id = "user-123"
    user.username = role
    user.is_superuser = False
    user.role = role
    user.is_active = True

    app.dependency_overrides[get_current_active_user] = lambda: user
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/v1/vpn/connect/lab"),
        ("post", "/api/v1/vpn/disconnect/lab"),
        ("get", "/api/v1/vpn/status"),
        ("post", "/api/v1/vpn/test"),
    ],
)
async def test_runtime_controls_require_operator_permissions(method: str, path: str):
    app = _make_app("user")

    manager = MagicMock()
    manager.connect = AsyncMock(return_value={"job_id": "job-1", "action": "connect", "type": "wireguard"})
    manager.disconnect = AsyncMock(return_value={"job_id": "job-2", "action": "disconnect", "type": "wireguard"})
    manager.status = AsyncMock(return_value={"job_id": "job-3", "action": "status", "type": "wireguard"})
    manager.test_connection = AsyncMock(return_value={"job_id": "job-4", "action": "test", "type": "wireguard"})

    with patch("app.api.routers.vpn._get_vpn_manager", return_value=manager):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await getattr(client, method)(path)

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_configs_remains_available_to_regular_users():
    app = _make_app("user")

    manager = MagicMock()
    manager.list_configs = AsyncMock(return_value=[{"name": "u_user-123_lab", "type": "wireguard", "size": 12}])

    with patch("app.api.routers.vpn._get_vpn_manager", return_value=manager):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/vpn/configs")

    assert response.status_code == 200
    assert response.json() == [{"name": "lab", "type": "wireguard", "path": "", "size": 12}]


@pytest.mark.asyncio
async def test_operator_can_connect_shared_runtime_with_owned_config():
    from app.api.routers import vpn as vpn_router

    app = _make_app("operator")

    manager = MagicMock()
    manager.connect = AsyncMock(return_value={"job_id": "job-1", "action": "connect", "type": "wireguard"})

    with (
        patch("app.api.routers.vpn._get_vpn_manager", return_value=manager),
        patch.object(vpn_router.settings, "VPN_ENABLED", True),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/v1/vpn/connect/lab")

    assert response.status_code == 200
    assert response.json()["job_id"] == "job-1"
    manager.connect.assert_awaited_once_with("u_user-123_lab")
