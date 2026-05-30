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

from spectra_auth.security import (
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
        from spectra_auth import security as _sec

        _sec._blacklisted_tokens.clear()
        _sec._user_token_blacklist.clear()
        _sec._blacklist_ready.set()

    @pytest.mark.asyncio
    async def test_logout_sets_invalidated_before_on_user(self):
        from spectra_api.api.routers.auth.login import logout

        token = create_access_token({"sub": "user-logout-invalidated"})
        user = MagicMock()
        user.username = "user-logout-invalidated"
        user.invalidated_before = None

        session = _mock_session_for_user(user)
        request = _make_request({"authorization": f"Bearer {token}"})
        response = MagicMock()
        response.delete_cookie = MagicMock()

        with patch("spectra_api.api.routers.auth.login.invalidate_token"):
            await logout(request=request, response=response, session=session)

        assert user.invalidated_before is not None
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_logout_blacklists_access_token(self):
        """logout calls invalidate_token, which places the token in the blacklist."""
        from spectra_api.api.routers.auth.login import logout

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
        from spectra_api.api.routers.auth.login import logout

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
        from spectra_api.api.routers.auth.login import refresh_token as refresh_endpoint

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
        from spectra_auth import security as _sec

        _sec._blacklisted_tokens.clear()
        _sec._user_token_blacklist.clear()
        _sec._blacklist_ready.set()

    @pytest.mark.asyncio
    async def test_cancel_mfa_blacklists_pending_token(self):
        from spectra_api.api.routers.auth.totp import cancel_mfa

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
        from spectra_api.api.routers.auth.totp import cancel_mfa

        token = create_access_token({"sub": "alice"})
        request = _make_request({"authorization": f"Bearer {token}"})

        await cancel_mfa.__wrapped__(request)

        assert not await is_token_blacklisted(token)

    @pytest.mark.asyncio
    async def test_cancel_mfa_without_token_returns_204(self):
        """Missing Authorization header returns 204 without error."""
        from spectra_api.api.routers.auth.totp import cancel_mfa

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
        from spectra_api.ui.pages import login_page

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
            patch("spectra_api.ui.pages.async_session_maker", return_value=_MockCtx()),
            patch("spectra_api.ui.pages.get_ui_user", return_value={"id": "u1", "username": "alice"}),
        ):
            resp = await login_page(request)

        assert resp.status_code == 302
        assert "/dashboard" in resp.headers.get("location", "")

    @pytest.mark.asyncio
    async def test_login_page_renders_for_anonymous_user(self):
        """Unauthenticated GET /login renders the login template."""
        from spectra_api.ui.pages import login_page

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
            patch("spectra_api.ui.pages.async_session_maker", return_value=_MockCtx()),
            patch("spectra_api.ui.pages.get_ui_user", return_value=None),
            patch("spectra_api.ui.pages.templates") as mock_tmpl,
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
        from spectra_api.ui.public import RegisterRequest, register_user

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

        with patch("spectra_api.ui.public.async_session_maker", maker), pytest.raises(HTTPException) as exc:
            await register_user.__wrapped__(request, body, Response())

        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_register_allowed_when_superuser_exists(self):
        from spectra_api.ui.public import RegisterRequest, register_user

        superuser_result = MagicMock()
        superuser_result.scalar_one_or_none.return_value = "admin-id"
        uniqueness_result = MagicMock()
        uniqueness_result.scalar_one_or_none.return_value = None  # no duplicate
        maker = _mock_session_ctx([superuser_result, uniqueness_result])
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
            patch("spectra_api.ui.public.async_session_maker", maker),
            patch("spectra_api.ui.public.PlanRepository.get_self_service_registration_plan", new=AsyncMock(return_value=None)),
            patch("spectra_system.audit.log_event", AsyncMock()),
        ):
            result = await register_user.__wrapped__(request, body, Response())

        assert "created" in result["detail"].lower()


class TestProfileEntitlementSource:
    @pytest.mark.asyncio
    async def test_current_profile_uses_active_subscription_plan_not_user_plan_id(self):
        from spectra_api.api.routers.auth.session import get_current_profile

        user = MagicMock()
        user.id = "user-1"
        user.username = "alice"
        user.email = "alice@example.com"
        user.role = "user"
        user.is_superuser = False
        user.mfa_enabled = False
        user.processing_restricted = False
        user.created_at = datetime.now(UTC)
        user.plan_id = "legacy-plan-id"

        plan = MagicMock()
        plan.id = "subscription-plan-id"
        plan.name = "starter"
        plan.display_name = "Starter"
        plan.features = {"manual_mode": True}
        plan.max_concurrent_missions = 2
        plan.max_missions_per_month = 20
        plan.max_targets = 10
        plan.max_storage_mb = 500
        plan.max_api_requests_per_hour = 100

        entitlement = MagicMock()
        entitlement.plan = plan

        subscription = MagicMock()
        subscription.plan_id = "subscription-plan-id"
        subscription.status = "active"
        subscription.payment_provider = "stripe"
        subscription.external_customer_id = "cus_123"

        subscription_result = MagicMock()
        subscription_result.first.return_value = (subscription, "Starter")
        prefs_result = MagicMock()
        prefs_result.scalar_one_or_none.return_value = None
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[subscription_result, prefs_result])

        with patch("spectra_api.api.routers.auth.session.get_user_entitlement", new=AsyncMock(return_value=entitlement)):
            profile = await get_current_profile.__wrapped__(
                request=_make_request(path="/api/v1/auth/me"),
                user=user,
                session=session,
            )

        assert profile["plan"]["id"] == "subscription-plan-id"
        assert profile["plan"]["name"] == "starter"
        assert profile["subscription"]["can_manage_billing"] is True
        assert profile["can_access_observability"] is False

    @pytest.mark.asyncio
    async def test_current_profile_returns_plan_none_without_entitlement(self):
        from spectra_api.api.routers.auth.session import get_current_profile

        user = MagicMock()
        user.id = "user-2"
        user.username = "bob"
        user.email = "bob@example.com"
        user.role = "user"
        user.is_superuser = False
        user.mfa_enabled = False
        user.processing_restricted = False
        user.created_at = datetime.now(UTC)
        user.plan_id = None

        subscription_result = MagicMock()
        subscription_result.first.return_value = None
        prefs_result = MagicMock()
        prefs_result.scalar_one_or_none.return_value = None
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[subscription_result, prefs_result])

        with patch("spectra_api.api.routers.auth.session.get_user_entitlement", new=AsyncMock(return_value=None)):
            profile = await get_current_profile.__wrapped__(
                request=_make_request(path="/api/v1/auth/me"),
                user=user,
                session=session,
            )

        assert profile["plan"] is None
        assert profile["subscription"] is None
        assert profile["can_access_observability"] is False

    @pytest.mark.asyncio
    async def test_current_profile_can_access_observability_for_superuser(self):
        from spectra_api.api.routers.auth.session import get_current_profile

        user = MagicMock()
        user.id = "user-su"
        user.username = "rootish"
        user.email = "root@example.com"
        user.role = "user"
        user.is_superuser = True
        user.mfa_enabled = False
        user.processing_restricted = False
        user.created_at = datetime.now(UTC)
        user.plan_id = None

        subscription_result = MagicMock()
        subscription_result.first.return_value = None
        prefs_result = MagicMock()
        prefs_result.scalar_one_or_none.return_value = None
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[subscription_result, prefs_result])

        with patch("spectra_api.api.routers.auth.session.get_user_entitlement", new=AsyncMock(return_value=None)):
            profile = await get_current_profile.__wrapped__(
                request=_make_request(path="/api/v1/auth/me"),
                user=user,
                session=session,
            )

        assert profile["can_access_observability"] is True

    @pytest.mark.asyncio
    async def test_current_profile_exposes_past_due_billing_recovery_without_entitlement(self):
        from spectra_api.api.routers.auth.session import get_current_profile

        user = MagicMock()
        user.id = "user-3"
        user.username = "carol"
        user.email = "carol@example.com"
        user.role = "user"
        user.is_superuser = False
        user.mfa_enabled = False
        user.processing_restricted = False
        user.created_at = datetime.now(UTC)
        user.plan_id = None

        subscription = MagicMock()
        subscription.plan_id = "plan-past-due"
        subscription.status = "past_due"
        subscription.payment_provider = "stripe"
        subscription.external_customer_id = "cus_past_due"

        subscription_result = MagicMock()
        subscription_result.first.return_value = (subscription, "Starter")
        prefs_result = MagicMock()
        prefs_result.scalar_one_or_none.return_value = None
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[subscription_result, prefs_result])

        with patch("spectra_api.api.routers.auth.session.get_user_entitlement", new=AsyncMock(return_value=None)):
            profile = await get_current_profile.__wrapped__(
                request=_make_request(path="/api/v1/auth/me"),
                user=user,
                session=session,
            )

        assert profile["plan"] is None
        assert profile["subscription"]["status"] == "past_due"
        assert profile["subscription"]["plan_display_name"] == "Starter"
        assert profile["subscription"]["can_manage_billing"] is True


# ---------------------------------------------------------------------------
# Email verification idempotency
# ---------------------------------------------------------------------------


class TestEmailVerifyIdempotency:
    """Verifying an already-verified email returns success (not an error)."""

    @pytest.mark.asyncio
    async def test_verify_already_verified_email_returns_success(self):
        from spectra_api.ui.public import verify_email_page

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
            patch("spectra_auth.security.verify_email_verification_token", return_value="user-id-123"),
            patch("spectra_api.ui.public.async_session_maker", return_value=_MockCtx()),
            patch("spectra_api.ui.public.templates") as mock_tmpl,
        ):
            mock_tmpl.TemplateResponse.return_value = MagicMock(status_code=200)
            await verify_email_page(request, token="fake-verify-token")

        args = mock_tmpl.TemplateResponse.call_args[0]
        call_context = args[1] if isinstance(args[0], str) else args[2]
        assert call_context["success"] is True
        assert "already" in call_context["message"].lower()
        mock_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_verify_fresh_email_sets_verified_flag_and_activates_user(self):
        from spectra_api.ui.public import verify_email_page

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
            patch("spectra_auth.security.verify_email_verification_token", return_value="user-id-123"),
            patch("spectra_api.ui.public.async_session_maker", return_value=_MockCtx()),
            patch("spectra_api.ui.public.invalidate_token", new_callable=AsyncMock),
            patch("spectra_api.ui.public.templates") as mock_tmpl,
        ):
            mock_tmpl.TemplateResponse.return_value = MagicMock(status_code=200)
            await verify_email_page(request, token="fresh-token")

        assert user.email_verified is True
        assert user.is_active is True
        mock_session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_verify_already_verified_inactive_user_reactivates_account(self):
        from spectra_api.ui.public import verify_email_page

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
            patch("spectra_auth.security.verify_email_verification_token", return_value="user-id-456"),
            patch("spectra_api.ui.public.async_session_maker", return_value=_MockCtx()),
            patch("spectra_api.ui.public.invalidate_token", new_callable=AsyncMock),
            patch("spectra_api.ui.public.templates") as mock_tmpl,
        ):
            mock_tmpl.TemplateResponse.return_value = MagicMock(status_code=200)
            await verify_email_page(request, token="inactive-token")

        assert user.email_verified is True
        assert user.is_active is True
        mock_session.commit.assert_awaited()
