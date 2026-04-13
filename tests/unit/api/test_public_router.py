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
        users_result = MagicMock()
        users_result.scalar.return_value = 0
        reviews_result = MagicMock()
        reviews_result.fetchall.return_value = []

        maker, _ = _mock_session_ctx([plan_result, findings_result, missions_result, users_result, reviews_result])

        with (
            patch("app.api.routers.public._get_user_from_cookie", return_value=None),
            patch("app.api.routers.public.async_session_maker", maker),
            patch("app.api.routers.public.templates") as mock_tmpl,
        ):
            mock_tmpl.TemplateResponse.return_value = HTMLResponse("<html></html>")
            resp = await client.get("/")
        assert resp.status_code == 200

    async def test_landing_template_adds_nonce_to_json_ld_script(self):
        from app.api.routers.public import templates

        request = Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "https",
                "path": "/",
                "raw_path": b"/",
                "query_string": b"",
                "headers": [],
                "client": ("127.0.0.1", 12345),
                "server": ("testserver", 443),
                "root_path": "",
            }
        )
        request.state.csp_nonce = "landing-nonce"

        html = templates.get_template("landing.html").render(
            request=request,
            plans=[],
            version="1.0.0",
            app_name="Spectra",
            stats={
                "total_findings": "0",
                "total_missions": "0",
                "uptime": "99.9%",
                "total_tools": "0",
            },
            reviews=[],
        )

        assert '<script nonce="landing-nonce" type="application/ld+json">' in html

    async def test_extract_legal_html_sanitizes_and_preserves_safe_legal_markup(self):
        from app.api.routers.public import _extract_legal_html

        html = _extract_legal_html(
            {
                "html": '<section><h2>Cookies</h2><table><tr><th scope="col">Cookie</th></tr><tr><td colspan="2">session</td></tr></table><script>alert(1)</script></section>',
            }
        )

        assert "<section>" in html
        assert "<table>" in html
        assert 'scope="col"' in html
        assert 'colspan="2"' in html
        assert "<script" not in html


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
        advisory_lock_result = MagicMock()
        latest_hash_result = MagicMock()
        latest_hash_result.scalar_one_or_none.return_value = None
        maker, _ = _mock_session_ctx([superuser_result, uniq, advisory_lock_result, latest_hash_result])

        body = RegisterRequest(username="newuser", email="new@example.com", password="StrongP4ss!")
        with (
            patch("app.api.routers.public.async_session_maker", maker),
            patch(
                "app.api.routers.public.PlanRepository.get_self_service_registration_plan",
                new=AsyncMock(return_value=None),
            ),
            patch("app.api.routers.public.sync_user_plan_mirror", new=AsyncMock()),
        ):
            result = await register_user.__wrapped__(_fake_request(), body, Response())
        assert "created" in result["detail"].lower()

    async def test_register_without_self_service_plan_leaves_user_unassigned(self):
        from app.api.routers.public import RegisterRequest, register_user
        from app.models.plan import Subscription
        from app.models.user import User

        superuser_result = MagicMock()
        superuser_result.scalar_one_or_none.return_value = "admin-id"
        uniq = MagicMock()
        uniq.scalar_one_or_none.return_value = None
        advisory_lock_result = MagicMock()
        latest_hash_result = MagicMock()
        latest_hash_result.scalar_one_or_none.return_value = None
        maker, mock_session = _mock_session_ctx([superuser_result, uniq, advisory_lock_result, latest_hash_result])

        body = RegisterRequest(username="unassigned", email="unassigned@example.com", password="StrongP4ss!")
        with (
            patch("app.api.routers.public.async_session_maker", maker),
            patch(
                "app.api.routers.public.PlanRepository.get_self_service_registration_plan",
                new=AsyncMock(return_value=None),
            ),
            patch("app.api.routers.public.sync_user_plan_mirror", new=AsyncMock()) as sync_mock,
        ):
            await register_user.__wrapped__(_fake_request(), body, Response())

        added = [call.args[0] for call in mock_session.add.call_args_list]
        assert any(isinstance(obj, User) and obj.plan_id is None for obj in added)
        assert not any(isinstance(obj, Subscription) for obj in added)
        sync_mock.assert_not_awaited()

    async def test_register_with_self_service_plan_creates_subscription(self):
        from app.api.routers.public import RegisterRequest, register_user
        from app.models.plan import Subscription

        superuser_result = MagicMock()
        superuser_result.scalar_one_or_none.return_value = "admin-id"
        uniq = MagicMock()
        uniq.scalar_one_or_none.return_value = None
        advisory_lock_result = MagicMock()
        latest_hash_result = MagicMock()
        latest_hash_result.scalar_one_or_none.return_value = None
        maker, mock_session = _mock_session_ctx([superuser_result, uniq, advisory_lock_result, latest_hash_result])

        plan = MagicMock()
        plan.id = "plan-self-service"

        body = RegisterRequest(username="assigned", email="assigned@example.com", password="StrongP4ss!")
        with (
            patch("app.api.routers.public.async_session_maker", maker),
            patch(
                "app.api.routers.public.PlanRepository.get_self_service_registration_plan",
                new=AsyncMock(return_value=plan),
            ),
            patch("app.api.routers.public.sync_user_plan_mirror", new=AsyncMock()) as sync_mock,
        ):
            await register_user.__wrapped__(_fake_request(), body, Response())

        added = [call.args[0] for call in mock_session.add.call_args_list]
        subscriptions = [obj for obj in added if isinstance(obj, Subscription)]
        assert len(subscriptions) == 1
        assert subscriptions[0].plan_id == "plan-self-service"
        assert subscriptions[0].status == "active"
        sync_mock.assert_awaited_once()

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
