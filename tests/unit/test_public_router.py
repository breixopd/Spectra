"""Tests for the public API router."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request, Response
from httpx import ASGITransport, AsyncClient
from starlette.responses import HTMLResponse

from app.api.routers.public import router


def _make_app() -> FastAPI:
    from app.core.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    limiter.enabled = False
    app.include_router(router)
    return app


def _mock_session_ctx(execute_results):
    """Build an async_session_maker mock that yields execute results in order."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=execute_results)
    mock_session.flush = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx), mock_session


def _fake_request():
    scope = {"type": "http", "method": "POST", "path": "/", "headers": [], "query_string": b""}
    return Request(scope)


@pytest_asyncio.fixture
async def client():
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as ac:
        yield ac


@pytest.mark.asyncio
class TestLandingPage:
    async def test_landing_page_redirects_authed(self, client):
        with patch("app.api.routers.public._get_user_from_cookie", return_value={"sub": "admin"}):
            resp = await client.get("/")
        assert resp.status_code == 302
        assert "/dashboard" in resp.headers.get("location", "")

    async def test_landing_page_renders(self, client):
        plan_result = MagicMock()
        plan_result.scalars.return_value.all.return_value = []

        findings_result = MagicMock()
        findings_result.scalar.return_value = 0
        missions_result = MagicMock()
        missions_result.scalar.return_value = 0
        reviews_result = MagicMock()
        reviews_result.fetchall.return_value = []

        maker, _ = _mock_session_ctx([plan_result, findings_result, missions_result, reviews_result])

        with (
            patch("app.api.routers.public._get_user_from_cookie", return_value=None),
            patch("app.api.routers.public.async_session_maker", maker),
            patch("app.api.routers.public.templates") as mock_tmpl,
        ):
            mock_tmpl.TemplateResponse.return_value = HTMLResponse("<html></html>")
            resp = await client.get("/")
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestPricingRedirect:
    async def test_pricing_redirects(self, client):
        resp = await client.get("/pricing")
        assert resp.status_code == 302
        assert "pricing" in resp.headers.get("location", "")


@pytest.mark.asyncio
class TestRegisterEndpoint:
    async def test_register_success(self):
        """Call register_user directly to bypass slowapi decorator."""
        from app.api.routers.public import RegisterRequest, register_user

        superuser_result = MagicMock()
        superuser_result.scalar_one_or_none.return_value = "admin-id"
        uniq = MagicMock()
        uniq.scalar_one_or_none.return_value = None
        plan = MagicMock()
        plan.scalar_one_or_none.return_value = None
        maker, _ = _mock_session_ctx([superuser_result, uniq, plan])

        body = RegisterRequest(username="newuser", email="new@example.com", password="StrongP4ss!")
        with patch("app.api.routers.public.async_session_maker", maker):
            result = await register_user.__wrapped__(_fake_request(), body, Response())
        assert "created" in result["detail"].lower()

    async def test_register_duplicate(self):
        from fastapi import HTTPException

        from app.api.routers.public import RegisterRequest, register_user

        superuser_result = MagicMock()
        superuser_result.scalar_one_or_none.return_value = "admin-id"
        uniq = MagicMock()
        uniq.scalar_one_or_none.return_value = "existing-id"
        maker, _ = _mock_session_ctx([superuser_result, uniq])

        body = RegisterRequest(username="taken", email="taken@example.com", password="StrongP4ss!")
        with patch("app.api.routers.public.async_session_maker", maker), pytest.raises(HTTPException) as exc_info:
            await register_user.__wrapped__(_fake_request(), body, Response())
        assert exc_info.value.status_code == 409

    async def test_register_invalid_payload_returns_422(self, client):
        resp = await client.post(
            "/api/public/register",
            json={"username": "short", "email": "invalid"},
        )

        assert resp.status_code == 422

    async def test_register_weak_password_validation(self):
        from pydantic import ValidationError

        from app.api.routers.public import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(username="user1", email="u@example.com", password="short")


@pytest.mark.asyncio
class TestPublicPlans:
    async def test_list_plans_empty(self, client):
        plan_result = MagicMock()
        plan_result.scalars.return_value.all.return_value = []
        maker, _ = _mock_session_ctx([plan_result])
        with patch("app.api.routers.public.async_session_maker", maker):
            resp = await client.get("/api/public/plans")
        assert resp.status_code == 200
        assert resp.json() == []
