"""Tests for app.api.dependencies — auth deps, plan rate limiter, plan enforcement."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    *,
    username="testuser",
    is_active=True,
    is_superuser=False,
    role="user",
    plan_id=None,
):
    user = MagicMock()
    user.username = username
    user.is_active = is_active
    user.is_superuser = is_superuser
    user.role = role
    user.plan_id = plan_id
    user.id = "user-123"
    return user


def _make_plan(*, max_concurrent_missions=None, max_targets=None, features=None):
    plan = MagicMock()
    plan.max_concurrent_missions = max_concurrent_missions
    plan.max_targets = max_targets
    plan.features = features
    return plan


def _make_transactional_session():
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock(return_value=session)
    transaction.__aexit__ = AsyncMock(return_value=None)
    session.begin = MagicMock(return_value=transaction)
    return session


# ---------------------------------------------------------------------------
# get_current_active_user
# ---------------------------------------------------------------------------


class TestGetCurrentActiveUser:
    @pytest.mark.asyncio
    async def test_active_user_passes(self):
        from app.api.dependencies import get_current_active_user

        user = _make_user(is_active=True)
        result = await get_current_active_user(current_user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_inactive_user_raises_403(self):
        from app.api.dependencies import get_current_active_user

        user = _make_user(is_active=False)
        with pytest.raises(HTTPException) as exc_info:
            await get_current_active_user(current_user=user)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# get_current_superuser
# ---------------------------------------------------------------------------


class TestGetCurrentSuperuser:
    @pytest.mark.asyncio
    async def test_superuser_passes(self):
        from app.api.dependencies import get_current_superuser

        user = _make_user(is_superuser=True, is_active=True)
        result = await get_current_superuser(current_user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_non_superuser_raises_403(self):
        from app.api.dependencies import get_current_superuser

        user = _make_user(is_superuser=False, is_active=True)
        with pytest.raises(HTTPException) as exc_info:
            await get_current_superuser(current_user=user)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# check_mission_limit
# ---------------------------------------------------------------------------


class TestCheckMissionLimit:
    @pytest.mark.asyncio
    async def test_admin_user_bypasses_limit(self):
        from app.api.dependencies import check_mission_limit

        user = _make_user(is_superuser=True, plan_id="plan-1")
        session = AsyncMock()
        # Should not raise even without mocking the plan
        await check_mission_limit(user, session)

    @pytest.mark.asyncio
    async def test_no_active_subscription_raises_403(self):
        from app.api.dependencies import check_mission_limit

        user = _make_user(plan_id=None)
        session = AsyncMock()
        with patch("app.api.dependencies.get_user_entitlement_plan", new=AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc_info:
                await check_mission_limit(user, session)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_within_limit_passes(self):
        from app.api.dependencies import check_mission_limit

        user = _make_user(plan_id="plan-1")
        plan = _make_plan(max_concurrent_missions=5)

        session = AsyncMock()
        # Second call: count active missions
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 2

        session.execute.return_value = mock_count_result
        with patch("app.api.dependencies.get_user_entitlement_plan", new=AsyncMock(return_value=plan)):
            await check_mission_limit(user, session)

    @pytest.mark.asyncio
    async def test_at_limit_raises_429(self):
        from app.api.dependencies import check_mission_limit

        user = _make_user(plan_id="plan-1")
        plan = _make_plan(max_concurrent_missions=3)

        session = AsyncMock()
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 3

        session.execute.return_value = mock_count_result

        with patch("app.api.dependencies.get_user_entitlement_plan", new=AsyncMock(return_value=plan)):
            with pytest.raises(HTTPException) as exc_info:
                await check_mission_limit(user, session)
        assert exc_info.value.status_code == 429


# ---------------------------------------------------------------------------
# check_target_limit
# ---------------------------------------------------------------------------


class TestCheckTargetLimit:
    @pytest.mark.asyncio
    async def test_admin_bypasses(self):
        from app.api.dependencies import check_target_limit

        user = _make_user(is_superuser=True, plan_id="plan-1")
        session = AsyncMock()
        await check_target_limit(user, session)

    @pytest.mark.asyncio
    async def test_within_limit(self):
        from app.api.dependencies import check_target_limit

        user = _make_user(plan_id="plan-1")
        plan = _make_plan(max_targets=100)

        session = AsyncMock()
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 10

        session.execute.return_value = mock_count_result
        with patch("app.api.dependencies.get_user_entitlement_plan", new=AsyncMock(return_value=plan)):
            await check_target_limit(user, session)

    @pytest.mark.asyncio
    async def test_at_limit_raises_429(self):
        from app.api.dependencies import check_target_limit

        user = _make_user(plan_id="plan-1")
        plan = _make_plan(max_targets=50)

        session = AsyncMock()
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 50

        session.execute.return_value = mock_count_result

        with patch("app.api.dependencies.get_user_entitlement_plan", new=AsyncMock(return_value=plan)):
            with pytest.raises(HTTPException) as exc_info:
                await check_target_limit(user, session)
        assert exc_info.value.status_code == 429


# ---------------------------------------------------------------------------
# check_feature_allowed
# ---------------------------------------------------------------------------


class TestCheckFeatureAllowed:
    @pytest.mark.asyncio
    async def test_admin_bypasses(self):
        from app.api.dependencies import check_feature_allowed

        user = _make_user(is_superuser=True, plan_id="plan-1")
        session = AsyncMock()
        await check_feature_allowed(user, session, "exploit_crafting")

    @pytest.mark.asyncio
    async def test_feature_enabled_passes(self):
        from app.api.dependencies import check_feature_allowed

        user = _make_user(plan_id="plan-1")
        plan = _make_plan(features={"exploit_crafting": True})

        session = AsyncMock()
        with patch("app.api.dependencies.get_user_entitlement_plan", new=AsyncMock(return_value=plan)):
            await check_feature_allowed(user, session, "exploit_crafting")

    @pytest.mark.asyncio
    async def test_feature_disabled_raises_403(self):
        from app.api.dependencies import check_feature_allowed

        user = _make_user(plan_id="plan-1")
        plan = _make_plan(features={"exploit_crafting": False})

        session = AsyncMock()
        with patch("app.api.dependencies.get_user_entitlement_plan", new=AsyncMock(return_value=plan)):
            with pytest.raises(HTTPException) as exc_info:
                await check_feature_allowed(user, session, "exploit_crafting")
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_missing_subscription_blocks_feature(self):
        from app.api.dependencies import check_feature_allowed

        user = _make_user(plan_id=None)
        session = AsyncMock()

        with patch("app.api.dependencies.get_user_entitlement_plan", new=AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc_info:
                await check_feature_allowed(user, session, "exploit_crafting")
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# enforce_api_rate_limit
# ---------------------------------------------------------------------------


class TestEnforceApiRateLimit:
    @pytest.mark.asyncio
    async def test_admin_bypasses_rate_limit(self):
        from app.api.dependencies import enforce_api_rate_limit

        user = _make_user(is_superuser=True)
        result = await enforce_api_rate_limit(user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_within_rate_limit(self):
        from app.api.dependencies import enforce_api_rate_limit

        user = _make_user()
        session = _make_transactional_session()
        mock_enforcer = MagicMock()
        mock_enforcer.check_api_quota = AsyncMock(return_value=(True, ""))
        mock_tracker = MagicMock()
        mock_tracker.record_api_request = AsyncMock()

        with (
            patch(
                "app.services.billing.quota_enforcer.QuotaEnforcer",
                return_value=mock_enforcer,
            ),
            patch(
                "app.services.billing.usage_tracker.UsageTracker",
                return_value=mock_tracker,
            ),
            patch("app.api.dependencies.async_session_maker", return_value=session),
            patch("app.api.dependencies.stable_lock_id", return_value=12345),
        ):
            result = await enforce_api_rate_limit(user=user)

        assert result is user
        session.execute.assert_awaited_once()
        mock_enforcer.check_api_quota.assert_awaited_once_with(str(user.id), session=session)
        mock_tracker.record_api_request.assert_awaited_once_with(str(user.id), session=session)

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_raises_429(self):
        from app.api.dependencies import enforce_api_rate_limit

        user = _make_user()
        session = _make_transactional_session()
        mock_enforcer = MagicMock()
        mock_enforcer.check_api_quota = AsyncMock(return_value=(False, "Hourly API limit reached: 100/100"))
        mock_enforcer.seconds_until_api_reset = AsyncMock(return_value=1800)
        mock_tracker = MagicMock()
        mock_tracker.record_api_request = AsyncMock()

        with (
            patch(
                "app.services.billing.quota_enforcer.QuotaEnforcer",
                return_value=mock_enforcer,
            ),
            patch(
                "app.services.billing.usage_tracker.UsageTracker",
                return_value=mock_tracker,
            ),
            patch("app.api.dependencies.async_session_maker", return_value=session),
            patch("app.api.dependencies.stable_lock_id", return_value=12345),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await enforce_api_rate_limit(user=user)
            assert exc_info.value.status_code == 429
            assert exc_info.value.headers["Retry-After"] == "1800"

        mock_tracker.record_api_request.assert_not_awaited()
