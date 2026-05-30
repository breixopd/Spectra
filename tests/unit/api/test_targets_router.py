"""Tests for the targets API router."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from spectra_api.api.routers.targets import router


def _fake_user(is_superuser: bool = False, user_id: str = "00000000-0000-4000-a000-000000000001"):
    user = MagicMock()
    user.id = user_id
    user.is_superuser = is_superuser
    user.role = "user"
    return user


def _fake_target(**overrides):
    defaults = {
        "id": "00000000-0000-4000-a000-100000000001",
        "address": "192.168.1.1",
        "description": "web server",
        "status": "pending",
        "os": "Linux",
        "user_id": "00000000-0000-4000-a000-000000000001",
        "created_at": datetime(2026, 1, 1, 12, 0),
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
    app.include_router(router, prefix="/api/v1")
    return app


@pytest_asyncio.fixture
async def client():
    app = _make_app()
    from spectra_api.api.dependencies import get_current_active_user
    from spectra_persistence.database import get_async_session

    user = _fake_user()
    app.dependency_overrides[get_current_active_user] = lambda: user

    mock_session = AsyncMock()
    mock_session.add = MagicMock()  # sync method — avoid AsyncMock coroutine warning

    async def _get_session():
        yield mock_session

    app.dependency_overrides[get_async_session] = _get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, mock_session, user


@pytest.mark.asyncio
class TestListTargets:
    async def test_list_targets_empty(self, client):
        ac, _session, _user = client
        from spectra_persistence.repositories.target import TargetRepository

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(TargetRepository, "count", AsyncMock(return_value=0))
            mp.setattr(TargetRepository, "find_many_by", AsyncMock(return_value=[]))
            resp = await ac.get("/api/v1/targets")

        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_list_targets_with_data(self, client):
        ac, _session, _user = client
        from spectra_persistence.repositories.target import TargetRepository

        target = _fake_target()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(TargetRepository, "count", AsyncMock(return_value=1))
            mp.setattr(TargetRepository, "find_many_by", AsyncMock(return_value=[target]))
            resp = await ac.get("/api/v1/targets")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["address"] == "192.168.1.1"


@pytest.mark.asyncio
class TestGetTarget:
    async def test_get_target_success(self, client):
        ac, _session, _user = client
        from spectra_persistence.repositories.target import TargetRepository

        target = _fake_target()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(TargetRepository, "get_by_id", AsyncMock(return_value=target))
            resp = await ac.get("/api/v1/targets/00000000-0000-4000-a000-100000000001")

        assert resp.status_code == 200
        assert resp.json()["id"] == "00000000-0000-4000-a000-100000000001"

    async def test_get_target_not_found(self, client):
        ac, _session, _user = client
        from spectra_persistence.repositories.target import TargetRepository

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(TargetRepository, "get_by_id", AsyncMock(return_value=None))
            resp = await ac.get("/api/v1/targets/00000000-0000-4000-a000-100000000099")

        assert resp.status_code == 404

    async def test_get_target_forbidden(self, client):
        ac, _session, _user = client
        from spectra_persistence.repositories.target import TargetRepository

        target = _fake_target(user_id="other-user")
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(TargetRepository, "get_by_id", AsyncMock(return_value=target))
            resp = await ac.get("/api/v1/targets/00000000-0000-4000-a000-100000000001")

        assert resp.status_code == 403


@pytest.mark.asyncio
class TestCreateTarget:
    async def test_create_target_success(self, client):
        ac, _session, _user = client
        from spectra_persistence.repositories.target import TargetRepository

        created = _fake_target()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(TargetRepository, "find_one_by", AsyncMock(return_value=None))
            mp.setattr(TargetRepository, "create", AsyncMock(return_value=created))
            mp.setattr("spectra_api.api.routers.targets.check_target_limit", AsyncMock())
            resp = await ac.post(
                "/api/v1/targets",
                json={
                    "address": "192.168.1.1",
                    "description": "web server",
                },
            )

        assert resp.status_code == 201
        assert resp.json()["address"] == "192.168.1.1"

    async def test_create_target_duplicate(self, client):
        ac, _session, _ = client
        from spectra_persistence.repositories.target import TargetRepository

        existing = _fake_target()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(TargetRepository, "find_one_by", AsyncMock(return_value=existing))
            mp.setattr("spectra_api.api.routers.targets.check_target_limit", AsyncMock())
            resp = await ac.post(
                "/api/v1/targets",
                json={
                    "address": "192.168.1.1",
                },
            )

        assert resp.status_code == 400

    async def test_create_target_invalid_address(self, client):
        ac, _, _ = client
        resp = await ac.post("/api/v1/targets", json={"address": ""})
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestDeleteTarget:
    async def test_delete_target_success(self, client):
        ac, _session, _ = client
        from spectra_persistence.repositories.target import TargetRepository

        target = _fake_target()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(TargetRepository, "get_by_id", AsyncMock(return_value=target))
            mp.setattr(TargetRepository, "delete", AsyncMock())
            resp = await ac.delete("/api/v1/targets/00000000-0000-4000-a000-100000000001")

        assert resp.status_code == 204

    async def test_delete_target_not_found(self, client):
        ac, _session, _ = client
        from spectra_persistence.repositories.target import TargetRepository

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(TargetRepository, "get_by_id", AsyncMock(return_value=None))
            resp = await ac.delete("/api/v1/targets/00000000-0000-4000-a000-100000000099")

        assert resp.status_code == 404


@pytest.mark.asyncio
class TestTargetFindings:
    async def test_list_findings_scoped_to_current_user(self, client):
        ac, _session, _user = client
        from spectra_persistence.repositories.finding import FindingRepository
        from spectra_persistence.repositories.target import TargetRepository

        target = _fake_target()
        mock_find = AsyncMock(return_value=[])

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(TargetRepository, "get_by_id", AsyncMock(return_value=target))
            mp.setattr(FindingRepository, "find_by_target", mock_find)
            resp = await ac.get("/api/v1/targets/00000000-0000-4000-a000-100000000001/findings")

        assert resp.status_code == 200
        mock_find.assert_awaited_once()
        assert mock_find.await_args.kwargs["target_id"] == "00000000-0000-4000-a000-100000000001"
        assert mock_find.await_args.kwargs["user_id"] == str(_user.id)

    async def test_superuser_list_findings_passes_no_user_filter(self, client):
        ac, _session, _user = client
        _user.is_superuser = True
        from spectra_persistence.repositories.finding import FindingRepository
        from spectra_persistence.repositories.target import TargetRepository

        target = _fake_target()
        mock_find = AsyncMock(return_value=[])

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(TargetRepository, "get_by_id", AsyncMock(return_value=target))
            mp.setattr(FindingRepository, "find_by_target", mock_find)
            resp = await ac.get("/api/v1/targets/00000000-0000-4000-a000-100000000001/findings")

        assert resp.status_code == 200
        mock_find.assert_awaited_once()
        assert mock_find.await_args.kwargs["target_id"] == "00000000-0000-4000-a000-100000000001"
        assert mock_find.await_args.kwargs["user_id"] is None
