"""Unit tests for webhook API endpoints (app/api/routers/webhooks.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routers.webhooks import router


def _fake_user(user_id: str = "u-1") -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.is_superuser = False
    user.is_active = True
    user.role = "operator"
    return user


def _fake_webhook(**overrides) -> MagicMock:
    defaults = {
        "id": "wh-1",
        "user_id": "u-1",
        "url": "https://example.com/hook",
        "events": ["mission.completed"],
        "secret": None,
        "description": "test hook",
        "is_active": True,
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
    app.include_router(router, prefix="/api/v1")
    return app


@pytest_asyncio.fixture
async def client():
    app = _make_app()
    from app.api.dependencies import get_current_active_user
    from app.core.database import get_async_session

    user = _fake_user()
    app.dependency_overrides[get_current_active_user] = lambda: user

    mock_session = AsyncMock()

    async def _get_session():
        yield mock_session

    app.dependency_overrides[get_async_session] = _get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, mock_session, user


@pytest.mark.asyncio
class TestCreateWebhook:
    async def test_create_webhook_success(self, client):
        ac, _session, _user = client
        wh = _fake_webhook()

        with patch("app.api.routers.webhooks.WebhookService") as MockSvc:
            MockSvc.return_value.register = AsyncMock(return_value=wh)

            resp = await ac.post(
                "/api/v1/webhooks",
                json={
                    "url": "https://example.com/hook",
                    "events": ["mission.completed"],
                },
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == "wh-1"
        assert data["url"] == "https://example.com/hook"
        assert data["is_active"] is True

    async def test_create_webhook_invalid_events(self, client):
        ac, _session, _user = client

        with patch("app.api.routers.webhooks.WebhookService") as MockSvc:
            MockSvc.return_value.register = AsyncMock(
                side_effect=ValueError("Unsupported webhook events: {'bad.event'}")
            )

            resp = await ac.post(
                "/api/v1/webhooks",
                json={
                    "url": "https://example.com/hook",
                    "events": ["bad.event"],
                },
            )

        assert resp.status_code == 422


@pytest.mark.asyncio
class TestListWebhooks:
    async def test_list_returns_user_webhooks(self, client):
        ac, _session, _user = client
        wh = _fake_webhook()

        with patch("app.api.routers.webhooks.WebhookService") as MockSvc:
            MockSvc.return_value.list_for_user = AsyncMock(return_value=[wh])

            resp = await ac.get("/api/v1/webhooks")

        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["id"] == "wh-1"

    async def test_list_empty(self, client):
        ac, _session, _user = client

        with patch("app.api.routers.webhooks.WebhookService") as MockSvc:
            MockSvc.return_value.list_for_user = AsyncMock(return_value=[])

            resp = await ac.get("/api/v1/webhooks")

        assert resp.status_code == 200
        assert resp.json() == []


@pytest.mark.asyncio
class TestUpdateWebhook:
    async def test_update_success(self, client):
        ac, _session, _user = client
        updated = _fake_webhook(url="https://new.example.com/hook")

        with patch("app.api.routers.webhooks.WebhookService") as MockSvc:
            MockSvc.return_value.update = AsyncMock(return_value=updated)

            resp = await ac.put(
                "/api/v1/webhooks/wh-1",
                json={"url": "https://new.example.com/hook"},
            )

        assert resp.status_code == 200
        assert resp.json()["url"] == "https://new.example.com/hook"

    async def test_update_not_found(self, client):
        ac, _session, _user = client

        with patch("app.api.routers.webhooks.WebhookService") as MockSvc:
            MockSvc.return_value.update = AsyncMock(return_value=None)

            resp = await ac.put(
                "/api/v1/webhooks/wh-nonexistent",
                json={"url": "https://new.example.com/hook"},
            )

        assert resp.status_code == 404

    async def test_update_invalid_events(self, client):
        ac, _session, _user = client

        with patch("app.api.routers.webhooks.WebhookService") as MockSvc:
            MockSvc.return_value.update = AsyncMock(side_effect=ValueError("Unsupported webhook events"))

            resp = await ac.put(
                "/api/v1/webhooks/wh-1",
                json={"events": ["nope"]},
            )

        assert resp.status_code == 422


@pytest.mark.asyncio
class TestDeleteWebhook:
    async def test_delete_success(self, client):
        ac, _session, _user = client

        with patch("app.api.routers.webhooks.WebhookService") as MockSvc:
            MockSvc.return_value.delete = AsyncMock(return_value=True)

            resp = await ac.delete("/api/v1/webhooks/wh-1")

        assert resp.status_code == 204

    async def test_delete_not_found(self, client):
        ac, _session, _user = client

        with patch("app.api.routers.webhooks.WebhookService") as MockSvc:
            MockSvc.return_value.delete = AsyncMock(return_value=False)

            resp = await ac.delete("/api/v1/webhooks/wh-nonexistent")

        assert resp.status_code == 404


@pytest.mark.asyncio
class TestTestWebhook:
    async def test_ping_success(self, client):
        ac, _session, _user = client
        wh = _fake_webhook()

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with (
            patch("app.api.routers.webhooks.WebhookService") as MockSvc,
            patch("httpx.AsyncClient") as MockHttpx,
        ):
            MockSvc.return_value.get_by_id = AsyncMock(return_value=wh)
            # Mock the httpx context manager
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_resp)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            MockHttpx.return_value = mock_client_instance

            resp = await ac.post("/api/v1/webhooks/wh-1/test")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["status_code"] == 200

    async def test_ping_not_found(self, client):
        ac, _session, _user = client

        with patch("app.api.routers.webhooks.WebhookService") as MockSvc:
            MockSvc.return_value.get_by_id = AsyncMock(return_value=None)

            resp = await ac.post("/api/v1/webhooks/wh-nonexistent/test")

        assert resp.status_code == 404

    async def test_ping_with_secret_sends_signature(self, client):
        ac, _session, _user = client
        wh = _fake_webhook(secret="mysecret")

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with (
            patch("app.api.routers.webhooks.WebhookService") as MockSvc,
            patch("httpx.AsyncClient") as MockHttpx,
        ):
            MockSvc.return_value.get_by_id = AsyncMock(return_value=wh)
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_resp)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            MockHttpx.return_value = mock_client_instance

            resp = await ac.post("/api/v1/webhooks/wh-1/test")

        assert resp.status_code == 200
        # Verify the post was called with signature header
        call_kwargs = mock_client_instance.post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert "X-Spectra-Signature" in headers


@pytest.mark.asyncio
class TestOwnershipValidation:
    async def test_get_webhook_of_other_user_returns_404(self, client):
        """Service scopes by user_id, so another user's webhook returns None."""
        ac, _session, _user = client

        with patch("app.api.routers.webhooks.WebhookService") as MockSvc:
            # Service returns None when user_id doesn't match
            MockSvc.return_value.get_by_id = AsyncMock(return_value=None)

            resp = await ac.get("/api/v1/webhooks/wh-other")

        assert resp.status_code == 404

    async def test_delete_webhook_of_other_user_returns_404(self, client):
        ac, _session, _user = client

        with patch("app.api.routers.webhooks.WebhookService") as MockSvc:
            MockSvc.return_value.delete = AsyncMock(return_value=False)

            resp = await ac.delete("/api/v1/webhooks/wh-other")

        assert resp.status_code == 404
