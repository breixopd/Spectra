"""Tests for admin monitoring endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _make_app():
    from app.api.routers.admin.monitoring import router
    from app.core.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    limiter.enabled = False
    app.include_router(router)
    return app


def _override_deps(app, role="admin"):
    from app.api.dependencies import get_current_active_user
    from app.core.database import get_async_session

    user = MagicMock()
    user.id = "u-1"
    user.username = "admin"
    user.is_superuser = role == "admin"
    user.role = role
    user.is_active = True
    user.mfa_enabled = True
    user.mfa_secret = "encrypted"
    user.hashed_password = "hashed"
    user.invalidated_before = None

    app.dependency_overrides[get_current_active_user] = lambda: user

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=0)))

    async def _get_session():
        yield mock_session

    app.dependency_overrides[get_async_session] = _get_session


@pytest.mark.asyncio
class TestMonitoringOverview:
    async def test_returns_overview(self):
        app = _make_app()
        _override_deps(app)

        with (
            patch("app.services.ai.cost_tracker.get_cost_trackers", return_value={}),
            patch("app.api.routers.admin.monitoring.get_metrics_store") as mock_ms,
        ):
            mock_ms.return_value.get_history.return_value = []
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/v1/admin/monitoring/overview")
            assert resp.status_code == 200
            data = resp.json()
            assert "system" in data
            assert "missions" in data
            assert "llm" in data


@pytest.mark.asyncio
class TestMonitoringTrends:
    async def test_returns_trends(self):
        app = _make_app()
        _override_deps(app)

        with patch("app.api.routers.admin.monitoring.get_metrics_store") as mock_ms:
            mock_ms.return_value.get_history.return_value = [{"value": 1}]
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/v1/admin/monitoring/trends?minutes=30")
            assert resp.status_code == 200
            data = resp.json()
            assert data["window_minutes"] == 30


@pytest.mark.asyncio
class TestMonitoringExport:
    async def test_export_json(self):
        app = _make_app()
        _override_deps(app)

        with patch("app.api.routers.admin.monitoring.get_metrics_store") as mock_ms:
            mock_ms.return_value.get_history.return_value = []
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/v1/admin/monitoring/export?format=json")
            assert resp.status_code == 200
            assert "application/json" in resp.headers.get("content-type", "")

    async def test_export_csv(self):
        app = _make_app()
        _override_deps(app)

        with patch("app.api.routers.admin.monitoring.get_metrics_store") as mock_ms:
            mock_ms.return_value.get_history.return_value = []
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/v1/admin/monitoring/export?format=csv")
            assert resp.status_code == 200
            assert "text/csv" in resp.headers.get("content-type", "")
