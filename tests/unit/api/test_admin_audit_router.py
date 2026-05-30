"""Tests for the admin audit log router."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from spectra_api.api.routers.admin.audit import router


def _fake_user(role: str = "admin", user_id: str = "u-1"):
    user = MagicMock()
    user.id = user_id
    user.is_superuser = role == "admin"
    user.role = role
    return user


def _fake_audit_row(**overrides):
    defaults = {
        "id": "a-1",
        "user_id": "u-1",
        "event_type": "LOGIN",
        "details": "User logged in",
        "ip_address": "10.0.0.1",
        "created_at": datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    }
    defaults.update(overrides)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_app() -> FastAPI:
    from spectra_auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    limiter.enabled = False
    app.include_router(router)
    return app


def _override_deps(app: FastAPI, user, mock_session):
    from spectra_api.api.dependencies import get_current_active_user
    from spectra_persistence.database import get_async_session

    app.dependency_overrides[get_current_active_user] = lambda: user

    async def _get_session():
        yield mock_session

    app.dependency_overrides[get_async_session] = _get_session


def _make_session_with_rows(rows, total: int = 1):
    """Create a mock session that returns audit rows for selects."""
    mock_session = AsyncMock()

    scalar_mock = MagicMock()
    scalar_mock.scalar.return_value = total

    scalars_mock = MagicMock()
    scalars_mock.scalars.return_value = MagicMock(all=MagicMock(return_value=rows))

    call_count = 0

    async def _execute(stmt):
        nonlocal call_count
        call_count += 1
        # First execute is count, second is the data query
        if call_count % 2 == 1:
            return scalar_mock
        return scalars_mock

    mock_session.execute = _execute
    return mock_session


# ---------------------------------------------------------------------------
# GET /api/admin/audit-logs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListAuditLogs:
    async def test_list_audit_logs_admin(self):
        app = _make_app()
        user = _fake_user(role="admin")
        row = _fake_audit_row()
        mock_session = _make_session_with_rows([row], total=1)
        _override_deps(app, user, mock_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/admin/audit-logs")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["event_type"] == "LOGIN"

    async def test_list_audit_logs_pagination(self):
        app = _make_app()
        user = _fake_user(role="admin")
        mock_session = _make_session_with_rows([], total=0)
        _override_deps(app, user, mock_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/admin/audit-logs?page=2&per_page=10")

        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 2
        assert data["per_page"] == 10

    async def test_list_audit_logs_non_admin_forbidden(self):
        app = _make_app()
        user = _fake_user(role="user")
        mock_session = AsyncMock()
        _override_deps(app, user, mock_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/admin/audit-logs")

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/admin/stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAdminStats:
    async def test_admin_stats_ok(self):
        app = _make_app()
        user = _fake_user(role="admin")

        mock_session = AsyncMock()

        scalar_count = MagicMock()
        scalar_count.scalar.return_value = 5

        role_result = MagicMock()
        role_result.all.return_value = [("admin", 1), ("staff", 3), ("user", 1)]

        call_index = 0

        async def _execute(stmt):
            nonlocal call_index
            call_index += 1
            if call_index <= 5:
                return scalar_count
            return role_result

        mock_session.execute = _execute
        _override_deps(app, user, mock_session)

        transport = ASGITransport(app=app)
        with patch("spectra_ai_core.gateway.service_registry.get_service_registry") as mock_reg:
            mock_reg.return_value.get_service_topology.return_value = {}
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/admin/stats")

        assert resp.status_code == 200
        data = resp.json()
        assert "total_users" in data
        assert "role_counts" in data
        assert data["smtp_configured"] is False
        assert "smtp_host" not in data

    async def test_admin_stats_mission_count_raises_oserror(self):
        app = _make_app()
        user = _fake_user(role="admin")

        scalar_count = MagicMock()
        scalar_count.scalar.return_value = 5

        role_result = MagicMock()
        role_result.all.return_value = [("admin", 1), ("staff", 3), ("user", 1)]

        call_index = 0

        async def _execute(stmt):
            nonlocal call_index
            call_index += 1
            # total_users(1), active_users(2), total_plans(3), total_missions(4), total_audit_events(5), role_result(6)
            if call_index == 4:
                raise OSError("db closed")
            if call_index <= 5:
                return scalar_count
            return role_result

        mock_session = AsyncMock()
        mock_session.execute = _execute
        _override_deps(app, user, mock_session)

        transport = ASGITransport(app=app)
        with patch("spectra_ai_core.gateway.service_registry.get_service_registry") as mock_reg:
            mock_reg.return_value.get_service_topology.return_value = {}
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/admin/stats")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_missions"] == 0

    async def test_admin_stats_non_admin_forbidden(self):
        app = _make_app()
        user = _fake_user(role="user")
        mock_session = AsyncMock()
        _override_deps(app, user, mock_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/admin/stats")

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Auth: no token → 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAuditNoAuth:
    async def test_audit_logs_no_token(self):
        app = _make_app()
        from spectra_persistence.database import get_async_session

        mock_session = AsyncMock()

        async def _get_session():
            yield mock_session

        app.dependency_overrides[get_async_session] = _get_session

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/admin/audit-logs")

        assert resp.status_code == 401

    async def test_admin_stats_no_token(self):
        app = _make_app()
        from spectra_persistence.database import get_async_session

        mock_session = AsyncMock()

        async def _get_session():
            yield mock_session

        app.dependency_overrides[get_async_session] = _get_session

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/admin/stats")

        assert resp.status_code == 401
