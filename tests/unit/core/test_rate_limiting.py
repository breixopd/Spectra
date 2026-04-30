"""Tests for plan-based rate limiting and the enforce_api_rate_limit dependency."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request


def _make_user(is_superuser=False, role="user", plan_id="plan-1", user_id="u-1"):
    user = MagicMock()
    user.id = user_id
    user.is_superuser = is_superuser
    user.role = role
    user.plan_id = plan_id
    user.is_active = True
    return user


def _make_transactional_session():
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock(return_value=session)
    transaction.__aexit__ = AsyncMock(return_value=None)
    session.begin = MagicMock(return_value=transaction)
    return session


def _make_request(headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/test",
            "headers": headers or [],
            "client": ("127.0.0.1", 12345),
        }
    )


def test_rate_limit_identifier_handles_invalid_bearer_token():
    from app.auth.rate_limit import get_user_identifier

    request = _make_request(headers=[(b"authorization", b"Bearer not-a-jwt")])

    assert get_user_identifier(request) == "invalid:127.0.0.1"


# ---------------------------------------------------------------------------
# enforce_api_rate_limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enforce_rate_limit_allows_within_limit():
    """User within plan limit passes through."""
    from app.api.dependencies import enforce_api_rate_limit

    user = _make_user()
    session = _make_transactional_session()

    mock_enforcer = MagicMock()
    mock_enforcer.check_api_quota = AsyncMock(return_value=(True, ""))
    mock_enforcer.seconds_until_api_reset = AsyncMock(return_value=3600)

    mock_tracker = MagicMock()
    mock_tracker.record_api_request = AsyncMock()

    with (
        patch("app.services.billing.quota_enforcer.QuotaEnforcer", return_value=mock_enforcer),
        patch("app.services.billing.usage_tracker.UsageTracker", return_value=mock_tracker),
        patch("app.api.dependencies.async_session_maker", return_value=session),
        patch("app.api.dependencies.stable_lock_id", return_value=12345),
    ):
        result = await enforce_api_rate_limit(user=user)

    assert result is user
    mock_enforcer.check_api_quota.assert_awaited_once_with(str(user.id), session=session)
    mock_tracker.record_api_request.assert_awaited_once_with(str(user.id), session=session)


@pytest.mark.asyncio
async def test_enforce_rate_limit_blocks_over_limit():
    """User over plan limit gets 429."""
    from app.api.dependencies import enforce_api_rate_limit

    user = _make_user()
    session = _make_transactional_session()

    mock_enforcer = MagicMock()
    mock_enforcer.check_api_quota = AsyncMock(return_value=(False, "Hourly API limit reached: 100/100"))
    mock_enforcer.seconds_until_api_reset = AsyncMock(return_value=1800)
    mock_tracker = MagicMock()
    mock_tracker.record_api_request = AsyncMock()

    with (
        patch("app.services.billing.quota_enforcer.QuotaEnforcer", return_value=mock_enforcer),
        patch("app.services.billing.usage_tracker.UsageTracker", return_value=mock_tracker),
        patch("app.api.dependencies.async_session_maker", return_value=session),
        patch("app.api.dependencies.stable_lock_id", return_value=12345),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await enforce_api_rate_limit(user=user)

    assert exc_info.value.status_code == 429
    assert "limit" in exc_info.value.detail.lower()
    mock_tracker.record_api_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_enforce_rate_limit_skips_admin():
    """Admin users bypass rate limiting entirely."""
    from app.api.dependencies import enforce_api_rate_limit

    admin = _make_user(is_superuser=True)

    # Admin bypasses before UsageTracker is ever instantiated
    result = await enforce_api_rate_limit(user=admin)
    assert result is admin


@pytest.mark.asyncio
async def test_enforce_rate_limit_skips_admin_role():
    """Users with role='admin' bypass rate limiting."""
    from app.api.dependencies import enforce_api_rate_limit

    admin = _make_user(is_superuser=False, role="admin")

    result = await enforce_api_rate_limit(user=admin)
    assert result is admin


# ---------------------------------------------------------------------------
# UsageTracker.check_rate_limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_rate_limit_no_subscription_returns_false():
    """User without subscription is not within limit."""
    from app.services.billing.usage_tracker import UsageTracker

    tracker = UsageTracker()

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.services.billing.usage_tracker.async_session_maker", return_value=mock_session),
        patch("app.services.billing.usage_tracker.get_user_entitlement", new=AsyncMock(return_value=None)),
    ):
        within, current, maximum = await tracker.check_rate_limit("user-1", "api_requests")

    assert within is False
    assert current == 0
    assert maximum == 0
    mock_session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_rate_limit_within_plan():
    """User within plan limits gets (True, current, max)."""
    from app.services.billing.usage_tracker import UsageTracker

    tracker = UsageTracker()

    mock_plan = MagicMock()
    mock_plan.max_api_requests_per_hour = 1000

    entitlement = MagicMock()
    entitlement.plan = mock_plan

    mock_record = MagicMock()
    mock_record.api_requests = 50

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_record
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.services.billing.usage_tracker.async_session_maker", return_value=mock_session),
        patch("app.services.billing.usage_tracker.get_user_entitlement", new=AsyncMock(return_value=entitlement)),
        patch("app.services.billing.usage_tracker.telemetry"),
    ):
            within, current, maximum = await tracker.check_rate_limit("user-1", "api_requests")

    assert within is True
    assert current == 50
    assert maximum == 1000


@pytest.mark.asyncio
async def test_check_rate_limit_over_plan():
    """User at or over the plan limit gets (False, current, max)."""
    from app.services.billing.usage_tracker import UsageTracker

    tracker = UsageTracker()

    mock_plan = MagicMock()
    mock_plan.max_api_requests_per_hour = 100

    entitlement = MagicMock()
    entitlement.plan = mock_plan

    mock_record = MagicMock()
    mock_record.api_requests = 100  # at limit

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_record
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.services.billing.usage_tracker.async_session_maker", return_value=mock_session),
        patch("app.services.billing.usage_tracker.get_user_entitlement", new=AsyncMock(return_value=entitlement)),
        patch("app.services.billing.usage_tracker.telemetry"),
    ):
            within, current, maximum = await tracker.check_rate_limit("user-1", "api_requests")

    assert within is False
    assert current == 100
    assert maximum == 100


@pytest.mark.asyncio
async def test_check_rate_limit_no_plan_limit_always_allowed():
    """When plan has no limit (None), user is always within limit."""
    from app.services.billing.usage_tracker import UsageTracker

    tracker = UsageTracker()

    mock_plan = MagicMock()
    mock_plan.max_api_requests_per_hour = None

    entitlement = MagicMock()
    entitlement.plan = mock_plan

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.services.billing.usage_tracker.async_session_maker", return_value=mock_session),
        patch("app.services.billing.usage_tracker.get_user_entitlement", new=AsyncMock(return_value=entitlement)),
    ):
        within, _current, maximum = await tracker.check_rate_limit("user-1", "api_requests")

    assert within is True
    assert maximum == 0
    mock_session.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# RateLimits presets exist
# ---------------------------------------------------------------------------


def test_rate_limit_presets_defined():
    """RateLimits class has expected tier configurations."""
    from app.auth.rate_limit import RateLimits

    assert hasattr(RateLimits, "LOGIN")
    assert hasattr(RateLimits, "MISSION_START")
    assert hasattr(RateLimits, "API_DEFAULT")
    assert hasattr(RateLimits, "API_HEAVY")
    assert "minute" in RateLimits.LOGIN


# ---------------------------------------------------------------------------
# rate_limit_exceeded_handler
# ---------------------------------------------------------------------------


def _make_rate_limit_exc(limit_string: str):
    """Create a RateLimitExceeded with a proper Limit wrapper."""
    import limits as limits_lib
    from slowapi.errors import RateLimitExceeded
    from slowapi.wrappers import Limit

    item = limits_lib.parse(limit_string)
    limit = Limit(item, lambda r: "x", None, False, None, None, None, 1, False)
    return RateLimitExceeded(limit)


@pytest.mark.asyncio
async def test_rate_limit_exceeded_handler_returns_429():
    """Handler produces a 429 JSON response with Retry-After header."""
    from app.auth.rate_limit import rate_limit_exceeded_handler

    request = MagicMock()
    request.url.path = "/api/test"
    request.client.host = "127.0.0.1"
    request.headers.get.return_value = None

    exc = _make_rate_limit_exc("100/minute")

    with patch("app.auth.rate_limit.events"):
        response = await rate_limit_exceeded_handler(request, exc)

    assert response.status_code == 429
    assert response.headers.get("Retry-After") == "60"
    assert "X-RateLimit-Limit" in response.headers


@pytest.mark.asyncio
async def test_rate_limit_exceeded_handler_body_structure():
    """Handler JSON body has expected keys."""
    import json

    from app.auth.rate_limit import rate_limit_exceeded_handler

    request = MagicMock()
    request.url.path = "/api/missions"
    request.client.host = "10.0.0.1"
    request.headers.get.return_value = None

    exc = _make_rate_limit_exc("5/minute")

    with patch("app.auth.rate_limit.events"):
        response = await rate_limit_exceeded_handler(request, exc)

    body = json.loads(response.body.decode())
    assert body["error"] == "RATE_LIMIT_EXCEEDED"
    assert "retry_after_seconds" in body
    assert body["retry_after_seconds"] == 60


@pytest.mark.asyncio
async def test_main_api_429_handler_delegates_rate_limit_exceeded():
    """The app-level 429 handler must preserve SlowAPI's structured response."""
    import json

    from app.bootstrap.templates import templates
    from spectra_api.errors import make_error_handler

    request = MagicMock()
    request.url.path = "/api/v1/auth/token"
    request.client.host = "127.0.0.1"
    request.headers.get.return_value = None

    exc = _make_rate_limit_exc("5/minute")

    with patch("app.auth.rate_limit.events"):
        response = await make_error_handler(templates, 429, "Too many requests", "errors/429.html")(request, exc)

    body = json.loads(response.body.decode())
    assert response.status_code == 429
    assert response.headers.get("Retry-After") == "60"
    assert body["error"] == "RATE_LIMIT_EXCEEDED"
    assert body["retry_after_seconds"] == 60


# ---------------------------------------------------------------------------
# slowapi limiter config
# ---------------------------------------------------------------------------


def test_limiter_headers_enabled():
    """Limiter instance has rate limit response headers enabled."""
    from app.auth.rate_limit import limiter

    assert limiter._headers_enabled is True


def test_limiter_default_limits():
    """Limiter has a default limit configured."""
    from app.auth.rate_limit import limiter

    assert len(limiter._default_limits) > 0


# ---------------------------------------------------------------------------
# get_client_identifier / get_user_identifier
# ---------------------------------------------------------------------------


def test_get_client_identifier_with_client():
    from app.auth.rate_limit import get_client_identifier

    request = MagicMock()
    request.client.host = "192.168.1.1"
    assert get_client_identifier(request) == "192.168.1.1"


def test_get_client_identifier_without_client():
    from app.auth.rate_limit import get_client_identifier

    request = MagicMock()
    request.client = None
    assert get_client_identifier(request) == "unknown"


def test_get_user_identifier_from_state():
    from app.auth.rate_limit import get_user_identifier

    request = MagicMock()
    request.state.user.username = "testuser"
    assert get_user_identifier(request) == "user:testuser"


def test_get_user_identifier_falls_back_to_ip():
    from app.auth.rate_limit import get_user_identifier

    request = MagicMock()
    request.state = MagicMock(spec=[])  # no 'user' attribute
    request.headers.get.return_value = None
    request.client.host = "10.0.0.5"
    assert get_user_identifier(request) == "10.0.0.5"
