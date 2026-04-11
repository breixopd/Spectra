"""Tests for app.api.routers.admin.rollback endpoints."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routers.admin.rollback import router


def _fake_user(role: str = "admin", user_id: str = "u-admin-1"):
    user = MagicMock()
    user.id = user_id
    user.is_superuser = role == "admin"
    user.role = role
    return user


def _make_app() -> FastAPI:
    from app.core.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    limiter.enabled = False
    app.include_router(router)
    return app


def _override_deps(app: FastAPI, user, mock_session):
    from app.api.dependencies import get_current_active_user
    from app.core.database import get_async_session

    app.dependency_overrides[get_current_active_user] = lambda: user

    async def _get_session():
        yield mock_session

    app.dependency_overrides[get_async_session] = _get_session


def _make_snapshot(**overrides):
    defaults = {
        "id": "snap-1",
        "actor_user_id": "u-admin-1",
        "target_entity_type": "user",
        "target_entity_id": "u-target-1",
        "action": "update_role",
        "created_at": datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
    }
    defaults.update(overrides)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


@pytest.mark.asyncio
@patch("app.api.routers.admin.rollback.get_all_snapshots", new_callable=AsyncMock)
async def test_list_snapshots_as_admin(mock_get_all):
    snap = _make_snapshot()
    mock_get_all.return_value = [snap]

    app = _make_app()
    mock_session = AsyncMock()
    _override_deps(app, _fake_user("admin"), mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/rollback/snapshots")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "snap-1"
    assert data[0]["entity_type"] == "user"
    mock_get_all.assert_awaited_once_with(mock_session, limit=50)


@pytest.mark.asyncio
async def test_list_snapshots_as_viewer_forbidden():
    app = _make_app()
    mock_session = AsyncMock()
    _override_deps(app, _fake_user("user"), mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/rollback/snapshots")

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_snapshots_as_operator_forbidden():
    app = _make_app()
    mock_session = AsyncMock()
    _override_deps(app, _fake_user("user"), mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/rollback/snapshots")

    assert resp.status_code == 403


@pytest.mark.asyncio
@patch("app.api.routers.admin.rollback.rollback_snapshot", new_callable=AsyncMock)
async def test_apply_rollback_success(mock_rollback):
    mock_rollback.return_value = {"role": "staff"}

    app = _make_app()
    mock_session = AsyncMock()
    _override_deps(app, _fake_user("admin"), mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/rollback/snapshots/snap-1/rollback")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "rolled_back"
    assert body["restored"] == {"role": "staff"}
    mock_session.commit.assert_awaited()


@pytest.mark.asyncio
@patch("app.api.routers.admin.rollback.rollback_snapshot", new_callable=AsyncMock)
async def test_apply_rollback_value_error(mock_rollback):
    mock_rollback.side_effect = ValueError("bad snapshot")

    app = _make_app()
    mock_session = AsyncMock()
    _override_deps(app, _fake_user("admin"), mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/rollback/snapshots/snap-bad/rollback")

    assert resp.status_code == 400
    assert "failed" in resp.json()["detail"].lower()


@pytest.mark.asyncio
@patch("app.api.routers.admin.rollback.rollback_snapshot", new_callable=AsyncMock)
async def test_apply_rollback_unexpected_error(mock_rollback):
    mock_rollback.side_effect = RuntimeError("unexpected")

    app = _make_app()
    mock_session = AsyncMock()
    _override_deps(app, _fake_user("admin"), mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/rollback/snapshots/snap-1/rollback")

    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_apply_rollback_without_admin_forbidden():
    app = _make_app()
    mock_session = AsyncMock()
    _override_deps(app, _fake_user("user"), mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/rollback/snapshots/snap-1/rollback")

    assert resp.status_code == 403


@pytest.mark.asyncio
@patch("app.api.routers.admin.rollback.get_all_snapshots", new_callable=AsyncMock)
async def test_list_snapshots_custom_limit(mock_get_all):
    mock_get_all.return_value = []

    app = _make_app()
    mock_session = AsyncMock()
    _override_deps(app, _fake_user("admin"), mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/rollback/snapshots?limit=10")

    assert resp.status_code == 200
    mock_get_all.assert_awaited_once_with(mock_session, limit=10)


@pytest.mark.asyncio
async def test_list_snapshots_limit_exceeds_max():
    """Limit > 200 should fail validation."""
    app = _make_app()
    mock_session = AsyncMock()
    _override_deps(app, _fake_user("admin"), mock_session)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/rollback/snapshots?limit=999")

    assert resp.status_code == 422
