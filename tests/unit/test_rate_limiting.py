"""Tests for plan-based rate limiting and the enforce_api_rate_limit dependency."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException


def _make_user(is_superuser=False, role="user", plan_id="plan-1", user_id="u-1"):
    user = MagicMock()
    user.id = user_id
    user.is_superuser = is_superuser
    user.role = role
    user.plan_id = plan_id
    user.is_active = True
    return user


# ---------------------------------------------------------------------------
# enforce_api_rate_limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enforce_rate_limit_allows_within_limit():
    """User within plan limit passes through."""
    from app.api.dependencies import enforce_api_rate_limit

    user = _make_user()

    mock_tracker = MagicMock()
    mock_tracker.check_rate_limit = AsyncMock(return_value=(True, 5, 100))
    mock_tracker.record_api_request = AsyncMock()

    with patch("app.services.billing.usage_tracker.UsageTracker", return_value=mock_tracker):
        result = await enforce_api_rate_limit(user=user)

    assert result is user
    mock_tracker.record_api_request.assert_awaited_once_with(str(user.id))


@pytest.mark.asyncio
async def test_enforce_rate_limit_blocks_over_limit():
    """User over plan limit gets 429."""
    from app.api.dependencies import enforce_api_rate_limit

    user = _make_user()

    mock_tracker = MagicMock()
    mock_tracker.check_rate_limit = AsyncMock(return_value=(False, 100, 100))

    with patch("app.services.billing.usage_tracker.UsageTracker", return_value=mock_tracker):
        with pytest.raises(HTTPException) as exc_info:
            await enforce_api_rate_limit(user=user)

    assert exc_info.value.status_code == 429
    assert "rate limit" in exc_info.value.detail.lower()


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
    mock_sub_result = MagicMock()
    mock_sub_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_sub_result
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.billing.usage_tracker.async_session_maker", return_value=mock_session):
        within, current, maximum = await tracker.check_rate_limit("user-1", "api_requests")

    assert within is False
    assert current == 0
    assert maximum == 0


@pytest.mark.asyncio
async def test_check_rate_limit_within_plan():
    """User within plan limits gets (True, current, max)."""
    from app.services.billing.usage_tracker import UsageTracker

    tracker = UsageTracker()

    mock_plan = MagicMock()
    mock_plan.max_api_requests_per_hour = 1000

    mock_sub = MagicMock()
    mock_sub.plan_id = "plan-1"

    mock_record = MagicMock()
    mock_record.api_requests = 50

    mock_session = AsyncMock()

    call_count = 0

    async def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # subscription query
            result.scalar_one_or_none.return_value = mock_sub
        else:
            # usage record query
            result.scalar_one_or_none.return_value = mock_record
        return result

    mock_session.execute = mock_execute
    mock_session.get = AsyncMock(return_value=mock_plan)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.billing.usage_tracker.async_session_maker", return_value=mock_session):
        with patch("app.services.billing.usage_tracker.telemetry"):
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

    mock_sub = MagicMock()
    mock_sub.plan_id = "plan-1"

    mock_record = MagicMock()
    mock_record.api_requests = 100  # at limit

    mock_session = AsyncMock()

    call_count = 0

    async def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = mock_sub
        else:
            result.scalar_one_or_none.return_value = mock_record
        return result

    mock_session.execute = mock_execute
    mock_session.get = AsyncMock(return_value=mock_plan)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.billing.usage_tracker.async_session_maker", return_value=mock_session):
        with patch("app.services.billing.usage_tracker.telemetry"):
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

    mock_sub = MagicMock()
    mock_sub.plan_id = "plan-1"

    mock_session = AsyncMock()

    call_count = 0

    async def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            result.scalar_one_or_none.return_value = mock_sub
        else:
            result.scalar_one_or_none.return_value = None
        return result

    mock_session.execute = mock_execute
    mock_session.get = AsyncMock(return_value=mock_plan)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.billing.usage_tracker.async_session_maker", return_value=mock_session):
        within, current, maximum = await tracker.check_rate_limit("user-1", "api_requests")

    assert within is True
    assert maximum == 0


# ---------------------------------------------------------------------------
# RateLimits presets exist
# ---------------------------------------------------------------------------


def test_rate_limit_presets_defined():
    """RateLimits class has expected tier configurations."""
    from app.core.rate_limit import RateLimits

    assert hasattr(RateLimits, "LOGIN")
    assert hasattr(RateLimits, "MISSION_START")
    assert hasattr(RateLimits, "API_DEFAULT")
    assert hasattr(RateLimits, "API_HEAVY")
    assert "minute" in RateLimits.LOGIN
