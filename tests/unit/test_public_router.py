"""Tests for the public API router."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
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
        maker, _ = _mock_session_ctx([plan_result])

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

        uniq = MagicMock()
        uniq.scalar_one_or_none.return_value = None
        plan = MagicMock()
        plan.scalar_one_or_none.return_value = None
        maker, _ = _mock_session_ctx([uniq, plan])

        body = RegisterRequest(username="newuser", email="new@example.com", password="StrongP4ss!")
        with patch("app.api.routers.public.async_session_maker", maker):
            result = await register_user.__wrapped__(_fake_request(), body)
        assert "created" in result["detail"].lower()

    async def test_register_duplicate(self):
        from fastapi import HTTPException

        from app.api.routers.public import RegisterRequest, register_user

        uniq = MagicMock()
        uniq.scalar_one_or_none.return_value = "existing-id"
        maker, _ = _mock_session_ctx([uniq])

        body = RegisterRequest(username="taken", email="taken@example.com", password="StrongP4ss!")
        with patch("app.api.routers.public.async_session_maker", maker), pytest.raises(HTTPException) as exc_info:
            await register_user.__wrapped__(_fake_request(), body)
        assert exc_info.value.status_code == 409

    async def test_register_weak_password_validation(self):
        from pydantic import ValidationError

        from app.api.routers.public import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(username="user1", email="u@example.com", password="short")


@pytest.mark.asyncio
class TestForgotPassword:
    async def test_forgot_password_always_returns_success(self):
        from app.api.routers.public import ForgotPasswordRequest, forgot_password

        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = None
        maker, _ = _mock_session_ctx([user_result])

        body = ForgotPasswordRequest(email="nobody@example.com")
        with patch("app.api.routers.public.async_session_maker", maker):
            result = await forgot_password.__wrapped__(_fake_request(), body)
        assert "reset link" in result["detail"].lower()


@pytest.mark.asyncio
class TestResetPassword:
    async def test_reset_password_invalid_token(self):
        from fastapi import HTTPException

        from app.api.routers.public import ResetPasswordRequest, reset_password

        body = ResetPasswordRequest(token="bad-token", new_password="NewStr0ng!")
        with (
            patch("app.api.routers.public.decode_token", side_effect=Exception("bad")),
            pytest.raises(HTTPException) as exc_info,
        ):
            await reset_password.__wrapped__(_fake_request(), body)
        assert exc_info.value.status_code == 400

    async def test_reset_password_wrong_type(self):
        from fastapi import HTTPException

        from app.api.routers.public import ResetPasswordRequest, reset_password

        body = ResetPasswordRequest(token="tok", new_password="NewStr0ng!")
        with (
            patch("app.api.routers.public.decode_token", return_value={"type": "access", "sub": "user1"}),
            pytest.raises(HTTPException) as exc_info,
        ):
            await reset_password.__wrapped__(_fake_request(), body)
        assert exc_info.value.status_code == 400


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
