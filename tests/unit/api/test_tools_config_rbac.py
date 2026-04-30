"""RBAC for GET /api/v1/tools/{tool_id}/config (execution metadata)."""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from spectra_api.api.dependencies import get_current_active_user
from spectra_api.api.routers import tools as tools_mod
from app.auth.rate_limit import limiter
from spectra_tools_core.models import RegisteredTool, ToolConfig, ToolStatus

_MINIMAL_TOOL = {
    "id": "t1",
    "name": "T",
    "version": "1.0.0",
    "category": "discovery",
    "description": "d",
    "execution": {"command": "cmd", "args_template": "{target}", "timeout": 60},
    "parsing": {"format": "json", "mapping": {}},
    "ui": {"icon": "terminal", "color": "violet"},
}


class _FakeRegistry:
    def get_tool(self, tool_id: str):
        if tool_id != "t1":
            return None
        return RegisteredTool(config=ToolConfig.model_validate(_MINIMAL_TOOL), status=ToolStatus.READY)


def _make_app() -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    limiter.enabled = False
    app.include_router(tools_mod.router, prefix="/api/v1")
    fake_registry = _FakeRegistry()

    def _override_registry():
        return fake_registry

    app.dependency_overrides[tools_mod.get_tool_registry] = _override_registry
    return app


def _user(role: str, *, superuser: bool = False):
    u = MagicMock()
    u.id = 1
    u.role = role
    u.is_superuser = superuser
    u.is_active = True
    return u


@pytest.mark.asyncio
async def test_tool_config_forbidden_for_default_user():
    app = _make_app()
    app.dependency_overrides[get_current_active_user] = lambda: _user("user")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/tools/t1/config")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_tool_config_forbidden_for_staff_without_manage_tools():
    app = _make_app()
    app.dependency_overrides[get_current_active_user] = lambda: _user("staff")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/tools/t1/config")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_tool_config_ok_for_admin():
    app = _make_app()
    app.dependency_overrides[get_current_active_user] = lambda: _user("admin")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/tools/t1/config")
    assert resp.status_code == 200
    assert resp.json()["command"] == "cmd"


@pytest.mark.asyncio
async def test_tool_config_ok_for_superuser():
    app = _make_app()
    app.dependency_overrides[get_current_active_user] = lambda: _user("user", superuser=True)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/tools/t1/config")
    assert resp.status_code == 200
