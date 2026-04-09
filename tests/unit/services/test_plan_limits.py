"""Tests for plan limit enforcement."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException


def _make_user(user_id="user-1", is_superuser=False, role="operator", plan_id=None):
    u = MagicMock()
    u.id = user_id
    u.is_superuser = is_superuser
    u.role = role
    u.is_active = True
    u.plan_id = plan_id
    return u


def _make_plan(
    max_concurrent_missions=None,
    max_targets=None,
    features=None,
):
    p = MagicMock()
    p.max_concurrent_missions = max_concurrent_missions
    p.max_targets = max_targets
    p.features = features
    return p


# ---------------------------------------------------------------------------
# check_mission_limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCheckMissionLimit:
    """Plan-based concurrent mission cap."""

    async def test_no_plan_not_blocked(self):
        from app.api.dependencies import check_mission_limit

        user = _make_user(plan_id=None)
        session = AsyncMock()
        # Should not raise
        await check_mission_limit(user, session)

    async def test_admin_bypasses_limit(self):
        from app.api.dependencies import check_mission_limit

        user = _make_user(is_superuser=True, plan_id="plan-1")
        session = AsyncMock()
        await check_mission_limit(user, session)

    async def test_admin_role_bypasses_limit(self):
        from app.api.dependencies import check_mission_limit

        user = _make_user(role="admin", plan_id="plan-1")
        session = AsyncMock()
        await check_mission_limit(user, session)

    async def test_under_limit_allowed(self):
        from app.api.dependencies import check_mission_limit

        plan = _make_plan(max_concurrent_missions=3)
        user = _make_user(plan_id="plan-1")
        session = AsyncMock()

        # Mock plan lookup
        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = plan
        # Mock active count query  — returns 1
        count_result = MagicMock()
        count_result.scalar.return_value = 1

        session.execute = AsyncMock(side_effect=[plan_result, count_result])

        await check_mission_limit(user, session)

    async def test_at_limit_blocked_429(self):
        from app.api.dependencies import check_mission_limit

        plan = _make_plan(max_concurrent_missions=2)
        user = _make_user(plan_id="plan-1")
        session = AsyncMock()

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = plan
        count_result = MagicMock()
        count_result.scalar.return_value = 2

        session.execute = AsyncMock(side_effect=[plan_result, count_result])

        with pytest.raises(HTTPException) as exc_info:
            await check_mission_limit(user, session)
        assert exc_info.value.status_code == 429
        assert "max 2" in exc_info.value.detail

    async def test_plan_without_mission_cap_not_blocked(self):
        from app.api.dependencies import check_mission_limit

        plan = _make_plan(max_concurrent_missions=None)
        user = _make_user(plan_id="plan-1")
        session = AsyncMock()

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = plan
        session.execute = AsyncMock(return_value=plan_result)

        await check_mission_limit(user, session)


# ---------------------------------------------------------------------------
# check_target_limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCheckTargetLimit:
    """Plan-based target cap."""

    async def test_no_plan_not_blocked(self):
        from app.api.dependencies import check_target_limit

        user = _make_user(plan_id=None)
        session = AsyncMock()
        await check_target_limit(user, session)

    async def test_admin_bypasses_limit(self):
        from app.api.dependencies import check_target_limit

        user = _make_user(is_superuser=True, plan_id="plan-1")
        session = AsyncMock()
        await check_target_limit(user, session)

    async def test_under_limit_allowed(self):
        from app.api.dependencies import check_target_limit

        plan = _make_plan(max_targets=10)
        user = _make_user(plan_id="plan-1")
        session = AsyncMock()

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = plan
        count_result = MagicMock()
        count_result.scalar.return_value = 5

        session.execute = AsyncMock(side_effect=[plan_result, count_result])

        await check_target_limit(user, session)

    async def test_at_limit_blocked_429(self):
        from app.api.dependencies import check_target_limit

        plan = _make_plan(max_targets=3)
        user = _make_user(plan_id="plan-1")
        session = AsyncMock()

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = plan
        count_result = MagicMock()
        count_result.scalar.return_value = 3

        session.execute = AsyncMock(side_effect=[plan_result, count_result])

        with pytest.raises(HTTPException) as exc_info:
            await check_target_limit(user, session)
        assert exc_info.value.status_code == 429
        assert "max 3" in exc_info.value.detail

    async def test_plan_without_target_cap_not_blocked(self):
        from app.api.dependencies import check_target_limit

        plan = _make_plan(max_targets=None)
        user = _make_user(plan_id="plan-1")
        session = AsyncMock()

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = plan
        session.execute = AsyncMock(return_value=plan_result)

        await check_target_limit(user, session)


# ---------------------------------------------------------------------------
# check_feature_allowed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCheckFeatureAllowed:
    """Feature gating by plan."""

    async def test_no_plan_allows_all(self):
        from app.api.dependencies import check_feature_allowed

        user = _make_user(plan_id=None)
        session = AsyncMock()
        await check_feature_allowed(user, session, "advanced_scanning")

    async def test_admin_bypasses_feature_gate(self):
        from app.api.dependencies import check_feature_allowed

        user = _make_user(is_superuser=True, plan_id="plan-1")
        session = AsyncMock()
        await check_feature_allowed(user, session, "advanced_scanning")

    async def test_plan_with_no_features_dict_allows_all(self):
        from app.api.dependencies import check_feature_allowed

        plan = _make_plan(features=None)
        user = _make_user(plan_id="plan-1")
        session = AsyncMock()

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = plan
        session.execute = AsyncMock(return_value=plan_result)

        await check_feature_allowed(user, session, "advanced_scanning")

    async def test_feature_enabled_allowed(self):
        from app.api.dependencies import check_feature_allowed

        plan = _make_plan(features={"advanced_scanning": True})
        user = _make_user(plan_id="plan-1")
        session = AsyncMock()

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = plan
        session.execute = AsyncMock(return_value=plan_result)

        await check_feature_allowed(user, session, "advanced_scanning")

    async def test_feature_disabled_blocked_403(self):
        from app.api.dependencies import check_feature_allowed

        plan = _make_plan(features={"advanced_scanning": False})
        user = _make_user(plan_id="plan-1")
        session = AsyncMock()

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = plan
        session.execute = AsyncMock(return_value=plan_result)

        with pytest.raises(HTTPException) as exc_info:
            await check_feature_allowed(user, session, "advanced_scanning")
        assert exc_info.value.status_code == 403
        assert "advanced_scanning" in exc_info.value.detail

    async def test_unlisted_feature_defaults_to_allowed(self):
        from app.api.dependencies import check_feature_allowed

        plan = _make_plan(features={"other_feature": False})
        user = _make_user(plan_id="plan-1")
        session = AsyncMock()

        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = plan
        session.execute = AsyncMock(return_value=plan_result)

        # Feature not in dict → defaults to True (not blocked)
        await check_feature_allowed(user, session, "advanced_scanning")
