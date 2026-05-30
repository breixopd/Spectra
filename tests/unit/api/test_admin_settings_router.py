"""Unit tests for the typed admin settings router."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from spectra_api.api.routers.admin.settings import router as admin_settings_router


def _make_admin() -> MagicMock:
    user = MagicMock()
    user.id = "admin-1"
    user.username = "admin"
    user.email = "admin@example.com"
    user.role = "admin"
    user.is_active = True
    user.is_superuser = True
    user.created_at = datetime(2025, 1, 1, tzinfo=UTC)
    user.updated_at = datetime(2025, 1, 1, tzinfo=UTC)
    return user


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(admin_settings_router)

    from spectra_api.api.dependencies import get_current_active_user

    app.dependency_overrides[get_current_active_user] = _make_admin
    return app


class TestAdminSettingsRouter:
    @pytest.mark.asyncio
    async def test_get_admin_settings(self):
        app = _build_app()

        with patch("spectra_api.api.routers.admin.settings.get_current_settings", return_value={"MAINTENANCE_MODE": False}) as get_mock:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get("/api/admin/settings")

        assert resp.status_code == 200
        assert resp.json()["MAINTENANCE_MODE"] is False
        get_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_admin_settings_accepts_uppercase_payload(self):
        app = _build_app()
        mock_session = AsyncMock()

        from spectra_persistence.database import get_async_session

        app.dependency_overrides[get_async_session] = lambda: mock_session

        with (
            patch(
                "spectra_api.api.routers.admin.settings.apply_settings_update",
                new=AsyncMock(return_value={"status": "updated", "message": "ok"}),
            ) as apply_mock,
            patch("spectra_api.api.routers.admin.settings.audit_log_event", new=AsyncMock()) as audit_mock,
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.put("/api/admin/settings", json={"MAINTENANCE_MODE": True})

        assert resp.status_code == 200
        assert resp.json()["updated"] == ["MAINTENANCE_MODE"]
        payload = apply_mock.await_args.args[0]
        assert payload.maintenance_mode is True
        audit_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_admin_settings_rejects_lowercase_keys(self):
        app = _build_app()
        mock_session = AsyncMock()

        from spectra_persistence.database import get_async_session

        app.dependency_overrides[get_async_session] = lambda: mock_session

        with patch("spectra_api.api.routers.admin.settings.apply_settings_update", new=AsyncMock()) as apply_mock:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.put("/api/admin/settings", json={"maintenance_mode": True})

        assert resp.status_code == 422
        apply_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_admin_settings_rejects_unknown_uppercase_keys(self):
        app = _build_app()
        mock_session = AsyncMock()

        from spectra_persistence.database import get_async_session

        app.dependency_overrides[get_async_session] = lambda: mock_session

        with patch("spectra_api.api.routers.admin.settings.apply_settings_update", new=AsyncMock()) as apply_mock:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.put("/api/admin/settings", json={"MAINTENANCE_MODE": True, "UNKNOWN_SETTING": True})

        assert resp.status_code == 422
        apply_mock.assert_not_awaited()
