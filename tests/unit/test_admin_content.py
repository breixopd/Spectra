"""Tests for app.api.routers.admin.content CRUD endpoints."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routers.admin.content import router


def _fake_user(role: str = "admin"):
    user = MagicMock()
    user.id = "u-1"
    user.role = role
    user.is_superuser = role == "admin"
    return user


def _fake_content_item(**overrides):
    from datetime import UTC, datetime
    defaults = {
        "id": "c-1",
        "content_type": "changelog",
        "title": "v1.0",
        "content": {"body": "Initial release"},
        "is_active": True,
        "sort_order": 0,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


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


def _session_returning_scalars(items):
    mock_session = AsyncMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = items
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    mock_session.execute.return_value = result_mock
    return mock_session


def _session_returning_scalar_one(item):
    mock_session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = item
    mock_session.execute.return_value = result_mock
    return mock_session


@pytest.mark.asyncio
class TestListContent:
    async def test_list_all(self):
        app = _make_app()
        items = [_fake_content_item(), _fake_content_item(id="c-2", content_type="review")]
        mock_session = _session_returning_scalars(items)
        _override_deps(app, _fake_user(), mock_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/admin/content")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    async def test_list_by_type(self):
        app = _make_app()
        mock_session = _session_returning_scalars([_fake_content_item()])
        _override_deps(app, _fake_user(), mock_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/admin/content", params={"content_type": "changelog"})
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestCreateContent:
    async def test_create_success(self):
        app = _make_app()
        mock_session = AsyncMock()
        # refresh needs to be a no-op
        mock_session.refresh = AsyncMock()
        # After add + commit + refresh, the item gets an id
        created_item = _fake_content_item()

        original_add = mock_session.add

        def _capture_add(item):
            item.id = "c-new"

        mock_session.add = _capture_add
        _override_deps(app, _fake_user(), mock_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/api/admin/content", json={
                "content_type": "review",
                "title": "Q1 Review",
                "content": {"body": "Great quarter"},
            })
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "created"

    async def test_create_changelog(self):
        app = _make_app()
        mock_session = AsyncMock()
        mock_session.refresh = AsyncMock()
        mock_session.add = lambda item: setattr(item, 'id', 'c-cl')
        _override_deps(app, _fake_user(), mock_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/api/admin/content", json={
                "content_type": "changelog",
                "title": "v2.0",
                "content": {"changes": ["feature X"]},
            })
        assert resp.status_code == 201


@pytest.mark.asyncio
class TestUpdateContent:
    async def test_update_existing(self):
        app = _make_app()
        item = _fake_content_item()
        mock_session = _session_returning_scalar_one(item)
        _override_deps(app, _fake_user(), mock_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.put("/api/admin/content/c-1", json={
                "title": "Updated Title",
            })
        assert resp.status_code == 200
        assert resp.json()["status"] == "updated"

    async def test_update_not_found(self):
        app = _make_app()
        mock_session = _session_returning_scalar_one(None)
        _override_deps(app, _fake_user(), mock_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.put("/api/admin/content/nonexistent", json={
                "title": "x",
            })
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestDeleteContent:
    async def test_delete_existing(self):
        app = _make_app()
        item = _fake_content_item()
        mock_session = _session_returning_scalar_one(item)
        _override_deps(app, _fake_user(), mock_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.delete("/api/admin/content/c-1")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    async def test_delete_not_found(self):
        app = _make_app()
        mock_session = _session_returning_scalar_one(None)
        _override_deps(app, _fake_user(), mock_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.delete("/api/admin/content/nope")
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestPermissionEnforcement:
    async def test_viewer_gets_403(self):
        app = _make_app()
        mock_session = AsyncMock()
        _override_deps(app, _fake_user(role="viewer"), mock_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/admin/content")
        assert resp.status_code == 403

    async def test_operator_gets_403(self):
        app = _make_app()
        mock_session = AsyncMock()
        _override_deps(app, _fake_user(role="operator"), mock_session)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/api/admin/content", json={
                "content_type": "changelog",
                "content": {},
            })
        assert resp.status_code == 403
