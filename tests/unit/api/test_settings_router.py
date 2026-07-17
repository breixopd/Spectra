"""Tests for settings API endpoints (GET/POST /api/settings)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from spectra_api.api.dependencies import get_current_active_user
from spectra_api.api.routers import settings_runtime
from spectra_persistence.database import get_async_session
from spectra_persistence.models.user import User


def _make_user(is_superuser: bool = False, username: str = "testuser") -> User:
    user = MagicMock(spec=User)
    user.id = "u-1"
    user.username = username
    user.is_superuser = is_superuser
    user.is_active = True
    user.role = "admin" if is_superuser else "user"
    return user


def _build_app(current_user: User | None = None, db=None):
    app = FastAPI()
    app.include_router(settings_runtime.router)

    if current_user is not None:
        app.dependency_overrides[get_current_active_user] = lambda: current_user
    if db is not None:
        app.dependency_overrides[get_async_session] = lambda: db
    return app


@pytest.mark.asyncio
class TestGetSettings:
    @patch("spectra_api.services.system.settings_service.get_current_settings")
    async def test_get_settings_authenticated(self, mock_get):
        mock_get.return_value = {"tensorzero_gateway_url": "http://tensorzero:3000", "log_level": "DEBUG"}
        app = _build_app(_make_user(is_superuser=True))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/settings")

        assert resp.status_code == 200
        assert resp.json()["tensorzero_gateway_url"] == "http://tensorzero:3000"

    async def test_get_settings_unauthenticated(self):
        app = FastAPI()
        app.include_router(settings_runtime.router)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/settings")

        assert resp.status_code in (401, 403)


@pytest.mark.asyncio
class TestUpdateSettings:
    @patch("spectra_api.api.routers.settings_runtime.apply_settings_update", new_callable=AsyncMock)
    async def test_superuser_can_update(self, mock_apply):
        mock_apply.return_value = {"status": "updated", "message": "Settings updated and saved"}
        app = _build_app(_make_user(is_superuser=True), AsyncMock())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/settings", json={"log_level": "WARNING"})

        assert resp.status_code == 200
        assert resp.json()["status"] == "updated"

    async def test_non_superuser_cannot_update(self):
        app = _build_app(_make_user(is_superuser=False), AsyncMock())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/settings", json={"log_level": "WARNING"})

        assert resp.status_code == 403


@pytest.mark.asyncio
class TestSettingsValidation:
    @patch("spectra_api.api.routers.settings_runtime.apply_settings_update", new_callable=AsyncMock)
    async def test_invalid_shell_routing_mode_rejected(self, mock_apply):
        app = _build_app(_make_user(is_superuser=True), AsyncMock())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/settings", json={"shell_routing_mode": "invalid"})

        assert resp.status_code == 422

    @patch("spectra_api.api.routers.settings_runtime.apply_settings_update", new_callable=AsyncMock)
    async def test_invalid_log_level_rejected(self, mock_apply):
        app = _build_app(_make_user(is_superuser=True), AsyncMock())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/settings", json={"log_level": "INVALID_LEVEL"})

        assert resp.status_code == 422
