"""
Tests for authentication security behaviours.

Covers:
- Logout sets user.invalidated_before, blocking stale refresh tokens
- MFA cancel places the pending token in the blacklist
- Login page redirects already-authenticated users to /dashboard
- Registration is blocked before system setup is complete
- Email verification is idempotent for already-verified accounts
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from app.core.security import (
    create_access_token,
    create_refresh_token,
    is_token_blacklisted,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    headers: dict | None = None,
    path: str = "/",
    cookies: dict[str, str] | None = None,
) -> Request:
    """Build a minimal Starlette Request."""
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    if cookies:
        cookie_header = "; ".join(f"{key}={value}" for key, value in cookies.items())
        raw_headers.append((b"cookie", cookie_header.encode()))
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": raw_headers,
        "query_string": b"",
    }
    return Request(scope)


def _mock_session_for_user(user):
    """Return an AsyncSession mock that returns *user* for scalar_one_or_none."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session


def _mock_session_ctx(execute_results):
    """Build an async_session_maker mock that yields execute results in order."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=execute_results)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx)


# ---------------------------------------------------------------------------
# Logout revokes refresh tokens
# ---------------------------------------------------------------------------


class TestLogoutRevokesRefreshToken:
    """Logout sets user.invalidated_before, making refresh tokens invalid."""

    def setup_method(self):
        """Clear JWT blacklist module-level state to isolate each test."""
        from app.core import security as _sec

        _sec._blacklisted_tokens.clear()
        _sec._user_token_blacklist.clear()
        _sec._blacklist_ready.set()

    @pytest.mark.asyncio
    async def test_logout_sets_invalidated_before_on_user(self):
        from app.api.routers.auth import logout

        token = create_access_token({"sub": "user-logout-invalidated"})
        user = MagicMock()
        user.username = "user-logout-invalidated"
        user.invalidated_before = None

        session = _mock_session_for_user(user)
        request = _make_request({"authorization": f"Bearer {token}"})
        response = MagicMock()
        response.delete_cookie = MagicMock()

        with patch("app.api.routers.auth.login.invalidate_token"):
            await logout(request=request, response=response, session=session)

        assert user.invalidated_before is not None
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_logout_blacklists_access_token(self):
        """logout calls invalidate_token, which places the token in the blacklist."""
        from app.api.routers.auth import logout

        # Use a unique sub to guarantee a distinct token from other tests
        token = create_access_token({"sub": "user-logout-blacklist"})
        user = MagicMock()
        user.username = "user-logout-blacklist"
        user.invalidated_before = None

        session = _mock_session_for_user(user)
        request = _make_request({"authorization": f"Bearer {token}"})
        response = MagicMock()
        response.delete_cookie = MagicMock()

        await logout(request=request, response=response, session=session)

        assert await is_token_blacklisted(token)

    @pytest.mark.asyncio
    async def test_logout_uses_access_token_cookie_when_bearer_missing(self):
        from app.api.routers.auth import logout

        token = create_access_token({"sub": "user-logout-cookie"})
        user = MagicMock()
        user.username = "user-logout-cookie"
        user.invalidated_before = None

        session = _mock_session_for_user(user)
        request = _make_request(cookies={"access_token": token})
        response = MagicMock()
        response.delete_cookie = MagicMock()

        await logout(request=request, response=response, session=session)

        assert await is_token_blacklisted(token)
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_refresh_rejected_when_issued_before_invalidation(self):
        """Refresh token whose iat predates user.invalidated_before → 401."""
        from app.api.routers.auth import refresh_token as refresh_endpoint

        rt = create_refresh_token({"sub": "bob"})

        user = MagicMock()
        user.is_active = True
        # Place invalidated_before in the future so any token's iat is before it
        user.invalidated_before = datetime.now(UTC) + timedelta(hours=1)

        session = _mock_session_for_user(user)
        request = _make_request()
        response = MagicMock()

        with pytest.raises(HTTPException) as exc:
            await refresh_endpoint.__wrapped__(
                request=request,
                response=response,
                body_refresh_token=rt,
                session=session,
            )

        assert exc.value.status_code == 401
        assert "invalidated" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# MFA cancel invalidates pending token
# ---------------------------------------------------------------------------


class TestMfaCancelBlocklist:
    """cancel_mfa places the MFA-pending token in the JWT blacklist."""

    def setup_method(self):
        from app.core import security as _sec

        _sec._blacklisted_tokens.clear()
        _sec._user_token_blacklist.clear()
        _sec._blacklist_ready.set()

    @pytest.mark.asyncio
    async def test_cancel_mfa_blacklists_pending_token(self):
        from app.api.routers.auth import cancel_mfa

        token = create_access_token(
            {"sub": "alice", "mfa_pending": True},
            expires_delta=timedelta(minutes=5),
        )
        request = _make_request({"authorization": f"Bearer {token}"})

        await cancel_mfa.__wrapped__(request)

        assert await is_token_blacklisted(token)

    @pytest.mark.asyncio
    async def test_cancel_mfa_does_not_blacklist_normal_token(self):
        """A regular access token (no mfa_pending) is not blacklisted by cancel."""
        from app.api.routers.auth import cancel_mfa

        token = create_access_token({"sub": "alice"})
        request = _make_request({"authorization": f"Bearer {token}"})

        await cancel_mfa.__wrapped__(request)

        assert not await is_token_blacklisted(token)

    @pytest.mark.asyncio
    async def test_cancel_mfa_without_token_returns_204(self):
        """Missing Authorization header returns 204 without error."""
        from app.api.routers.auth import cancel_mfa

        request = _make_request()
        result = await cancel_mfa.__wrapped__(request)

        assert result.status_code == 204


# ---------------------------------------------------------------------------
# Login page redirects authenticated users
# ---------------------------------------------------------------------------


class TestLoginRedirectsAuthenticated:
    """GET /login with a valid auth cookie redirects to /dashboard."""

    @pytest.mark.asyncio
    async def test_login_page_redirects_authenticated_user(self):
        from app.api.routers.ui import login_page

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/login",
            "headers": [],
            "query_string": b"",
        }
        request = Request(scope)

        # DB returns a user ID (setup complete — no /setup redirect)
        db_result = MagicMock()
        db_result.scalar_one_or_none.return_value = "some-user-id"
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=db_result)

        class _MockCtx:
            async def __aenter__(self_inner):
                return mock_session

            async def __aexit__(self_inner, *a):
                pass

        with (
            patch("app.api.routers.ui.async_session_maker", return_value=_MockCtx()),
            patch("app.api.routers.ui.get_ui_user", return_value={"id": "u1", "username": "alice"}),
        ):
            resp = await login_page(request)

        assert resp.status_code == 302
        assert "/dashboard" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_login_page_renders_for_anonymous_user(self):
        """Unauthenticated GET /login renders the login template."""
        from app.api.routers.ui import login_page

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/login",
            "headers": [],
            "query_string": b"",
        }
        request = Request(scope)

        db_result = MagicMock()
        db_result.scalar_one_or_none.return_value = "some-user-id"
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=db_result)

        class _MockCtx:
            async def __aenter__(self_inner):
                return mock_session

            async def __aexit__(self_inner, *a):
                pass

        with (
            patch("app.api.routers.ui.async_session_maker", return_value=_MockCtx()),
            patch("app.api.routers.ui.get_ui_user", return_value=None),
            patch("app.api.routers.ui.templates") as mock_tmpl,
        ):
            mock_tmpl.TemplateResponse.return_value = MagicMock(status_code=200)
            resp = await login_page(request)

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Pre-setup registration blocked
# ---------------------------------------------------------------------------


class TestPreSetupRegistrationBlocked:
    """POST /api/public/register before a superuser exists returns 403."""

    @pytest.mark.asyncio
    async def test_register_blocked_when_no_superuser(self):
        from app.api.routers.public import RegisterRequest, register_user

        # Superuser check returns None — setup not complete
        superuser_result = MagicMock()
        superuser_result.scalar_one_or_none.return_value = None
        maker = _mock_session_ctx([superuser_result])

        body = RegisterRequest(username="attacker", email="a@a.com", password="StrongP4ss!")
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/public/register",
            "headers": [],
            "query_string": b"",
        }
        request = Request(scope)

        with patch("app.api.routers.public.async_session_maker", maker), pytest.raises(HTTPException) as exc:
            await register_user.__wrapped__(request, body, Response())

        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_register_allowed_when_superuser_exists(self):
        from app.api.routers.public import RegisterRequest, register_user

        superuser_result = MagicMock()
        superuser_result.scalar_one_or_none.return_value = "admin-id"
        uniqueness_result = MagicMock()
        uniqueness_result.scalar_one_or_none.return_value = None  # no duplicate
        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = None  # no default plan

        fallback_plan_result = MagicMock()
        fallback_plan_result.scalar_one_or_none.return_value = None
        maker = _mock_session_ctx([superuser_result, uniqueness_result, plan_result, fallback_plan_result])
        body = RegisterRequest(username="newuser", email="n@n.com", password="StrongP4ss!")
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/public/register",
            "headers": [],
            "query_string": b"",
        }
        request = Request(scope)

        with (
            patch("app.api.routers.public.async_session_maker", maker),
            patch("app.services.system.audit.log_event", AsyncMock()),
        ):
            result = await register_user.__wrapped__(request, body, Response())

        assert "created" in result["detail"].lower()


# ---------------------------------------------------------------------------
# Email verification idempotency
# ---------------------------------------------------------------------------


class TestEmailVerifyIdempotency:
    """Verifying an already-verified email returns success (not an error)."""

    @pytest.mark.asyncio
    async def test_verify_already_verified_email_returns_success(self):
        from app.api.routers.public import verify_email_page

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/verify-email",
            "headers": [],
            "query_string": b"",
        }
        request = Request(scope)

        user = MagicMock()
        user.email_verified = True
        user.is_active = True

        db_result = MagicMock()
        db_result.scalar_one_or_none.return_value = user
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=db_result)
        mock_session.commit = AsyncMock()

        class _MockCtx:
            async def __aenter__(self_inner):
                return mock_session

            async def __aexit__(self_inner, *a):
                pass

        with (
            patch("app.core.security.verify_email_verification_token", return_value="user-id-123"),
            patch("app.api.routers.public.async_session_maker", return_value=_MockCtx()),
            patch("app.api.routers.public.templates") as mock_tmpl,
        ):
            mock_tmpl.TemplateResponse.return_value = MagicMock(status_code=200)
            await verify_email_page(request, token="fake-verify-token")

        call_context = mock_tmpl.TemplateResponse.call_args[0][1]
        assert call_context["success"] is True
        assert "already" in call_context["message"].lower()
        mock_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_verify_fresh_email_sets_verified_flag_and_activates_user(self):
        from app.api.routers.public import verify_email_page

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/verify-email",
            "headers": [],
            "query_string": b"",
        }
        request = Request(scope)

        user = MagicMock()
        user.email_verified = False
        user.is_active = False

        db_result = MagicMock()
        db_result.scalar_one_or_none.return_value = user
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=db_result)
        mock_session.commit = AsyncMock()

        class _MockCtx:
            async def __aenter__(self_inner):
                return mock_session

            async def __aexit__(self_inner, *a):
                pass

        with (
            patch("app.core.security.verify_email_verification_token", return_value="user-id-123"),
            patch("app.api.routers.public.async_session_maker", return_value=_MockCtx()),
            patch("app.api.routers.public.invalidate_token", new_callable=AsyncMock),
            patch("app.api.routers.public.templates") as mock_tmpl,
        ):
            mock_tmpl.TemplateResponse.return_value = MagicMock(status_code=200)
            await verify_email_page(request, token="fresh-token")

        assert user.email_verified is True
        assert user.is_active is True
        mock_session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_verify_already_verified_inactive_user_reactivates_account(self):
        from app.api.routers.public import verify_email_page

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/verify-email",
            "headers": [],
            "query_string": b"",
        }
        request = Request(scope)

        user = MagicMock()
        user.email_verified = True
        user.is_active = False

        db_result = MagicMock()
        db_result.scalar_one_or_none.return_value = user
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=db_result)
        mock_session.commit = AsyncMock()

        class _MockCtx:
            async def __aenter__(self_inner):
                return mock_session

            async def __aexit__(self_inner, *a):
                pass

        with (
            patch("app.core.security.verify_email_verification_token", return_value="user-id-456"),
            patch("app.api.routers.public.async_session_maker", return_value=_MockCtx()),
            patch("app.api.routers.public.invalidate_token", new_callable=AsyncMock),
            patch("app.api.routers.public.templates") as mock_tmpl,
        ):
            mock_tmpl.TemplateResponse.return_value = MagicMock(status_code=200)
            await verify_email_page(request, token="inactive-token")

        assert user.email_verified is True
        assert user.is_active is True
        mock_session.commit.assert_awaited()
