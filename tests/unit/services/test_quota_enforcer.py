"""Tests for QuotaEnforcer."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_plan(**overrides):
    plan = MagicMock()
    plan.max_concurrent_missions = overrides.get("max_concurrent_missions", 2)
    plan.max_missions_per_month = overrides.get("max_missions_per_month", 10)
    plan.max_missions_per_day = overrides.get("max_missions_per_day", 0)
    plan.max_missions_per_week = overrides.get("max_missions_per_week", 0)
    plan.max_api_requests_per_hour = overrides.get("max_api_requests_per_hour", 100)
    plan.max_api_requests_per_day = overrides.get("max_api_requests_per_day", 0)
    plan.max_storage_mb = overrides.get("max_storage_mb", 500)
    return plan


def _mock_session(records=None, scalar_value=None):
    """Build an async context-manager session mock."""
    session = AsyncMock()
    result = MagicMock()

    if scalar_value is not None:
        result.scalar.return_value = scalar_value

    if records is not None:
        result.scalar_one_or_none.return_value = records
    else:
        result.scalar_one_or_none.return_value = None

    session.execute = AsyncMock(return_value=result)
    session.get = AsyncMock(return_value=None)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


@pytest.mark.asyncio
class TestCheckMissionQuota:
    async def test_allowed_when_under_concurrent_limit(self):
        from app.services.billing.quota_enforcer import QuotaEnforcer

        plan = _make_plan(max_concurrent_missions=5, max_missions_per_month=None)

        session = _mock_session()
        # First execute: concurrent count
        count_result = MagicMock()
        count_result.scalar.return_value = 2
        # Second execute: usage record (not reached since monthly is None)
        session.execute = AsyncMock(return_value=count_result)

        with patch("app.services.billing.quota_enforcer.async_session_maker", return_value=session):
            enforcer = QuotaEnforcer()
            allowed, reason = await enforcer.check_mission_quota("user-1", plan)

        assert allowed is True
        assert reason == ""

    async def test_blocked_when_at_concurrent_limit(self):
        from app.services.billing.quota_enforcer import QuotaEnforcer

        plan = _make_plan(max_concurrent_missions=2, max_missions_per_month=None)

        session = _mock_session()
        count_result = MagicMock()
        count_result.scalar.return_value = 2
        session.execute = AsyncMock(return_value=count_result)

        with patch("app.services.billing.quota_enforcer.async_session_maker", return_value=session):
            enforcer = QuotaEnforcer()
            allowed, reason = await enforcer.check_mission_quota("user-1", plan)

        assert allowed is False
        assert "Concurrent mission limit" in reason

    async def test_blocked_when_monthly_limit_reached(self):
        from app.services.billing.quota_enforcer import QuotaEnforcer

        plan = _make_plan(max_concurrent_missions=10, max_missions_per_month=5)

        session = _mock_session()
        # First call: concurrent count = 0
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        # Second call: usage record
        usage_record = MagicMock()
        usage_record.missions_started = 5
        usage_result = MagicMock()
        usage_result.scalar_one_or_none.return_value = usage_record

        locked_result = MagicMock()
        locked_result.scalar_one_or_none.return_value = MagicMock()
        advisory_lock_result = MagicMock()  # result of pg_advisory_xact_lock
        session.execute = AsyncMock(side_effect=[advisory_lock_result, locked_result, count_result, usage_result])

        with patch("app.services.billing.quota_enforcer.async_session_maker", return_value=session):
            enforcer = QuotaEnforcer()
            allowed, reason = await enforcer.check_mission_quota("user-1", plan)

        assert allowed is False
        assert "Monthly mission limit" in reason

    async def test_no_subscription_returns_false(self):
        from app.services.billing.quota_enforcer import QuotaEnforcer

        session = _mock_session()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

        with patch("app.services.billing.quota_enforcer.async_session_maker", return_value=session):
            enforcer = QuotaEnforcer()
            allowed, reason = await enforcer.check_mission_quota("user-1")

        assert allowed is False
        assert "No active subscription" in reason

    async def test_allowed_when_no_monthly_limit(self):
        from app.services.billing.quota_enforcer import QuotaEnforcer

        plan = _make_plan(max_concurrent_missions=10, max_missions_per_month=None)

        session = _mock_session()
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        session.execute = AsyncMock(return_value=count_result)

        with patch("app.services.billing.quota_enforcer.async_session_maker", return_value=session):
            enforcer = QuotaEnforcer()
            allowed, _reason = await enforcer.check_mission_quota("user-1", plan)

        assert allowed is True


@pytest.mark.asyncio
class TestCheckApiQuota:
    async def test_allowed_under_limit(self):
        from app.services.billing.quota_enforcer import QuotaEnforcer

        plan = _make_plan(max_api_requests_per_hour=100)

        session = _mock_session()
        record = MagicMock()
        record.api_requests = 50
        result = MagicMock()
        result.scalar_one_or_none.return_value = record
        session.execute = AsyncMock(return_value=result)

        with patch("app.services.billing.quota_enforcer.async_session_maker", return_value=session):
            enforcer = QuotaEnforcer()
            allowed, reason = await enforcer.check_api_quota("user-1", plan)

        assert allowed is True
        assert reason == ""

    async def test_blocked_at_limit(self):
        from app.services.billing.quota_enforcer import QuotaEnforcer

        plan = _make_plan(max_api_requests_per_hour=100)

        session = _mock_session()
        record = MagicMock()
        record.api_requests = 100
        result = MagicMock()
        result.scalar_one_or_none.return_value = record
        session.execute = AsyncMock(return_value=result)

        with patch("app.services.billing.quota_enforcer.async_session_maker", return_value=session):
            enforcer = QuotaEnforcer()
            allowed, reason = await enforcer.check_api_quota("user-1", plan)

        assert allowed is False
        assert "Hourly API limit" in reason

    async def test_no_record_means_allowed(self):
        from app.services.billing.quota_enforcer import QuotaEnforcer

        plan = _make_plan(max_api_requests_per_hour=100)

        session = _mock_session()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result)

        with patch("app.services.billing.quota_enforcer.async_session_maker", return_value=session):
            enforcer = QuotaEnforcer()
            allowed, _reason = await enforcer.check_api_quota("user-1", plan)

        assert allowed is True

    async def test_zero_limit_means_unlimited(self):
        from app.services.billing.quota_enforcer import QuotaEnforcer

        plan = _make_plan(max_api_requests_per_hour=0, max_api_requests_per_day=0)

        session = _mock_session()

        with patch("app.services.billing.quota_enforcer.async_session_maker", return_value=session):
            enforcer = QuotaEnforcer()
            allowed, _reason = await enforcer.check_api_quota("user-1", plan)

        assert allowed is True

    async def test_blocked_at_daily_limit_even_when_hourly_is_unlimited(self):
        from app.services.billing.quota_enforcer import QuotaEnforcer

        plan = _make_plan(max_api_requests_per_hour=0, max_api_requests_per_day=500)

        session = _mock_session()
        daily_record = MagicMock()
        daily_record.api_requests = 500
        daily_result = MagicMock()
        daily_result.scalar_one_or_none.return_value = daily_record
        session.execute = AsyncMock(return_value=daily_result)

        with patch("app.services.billing.quota_enforcer.async_session_maker", return_value=session):
            enforcer = QuotaEnforcer()
            allowed, reason = await enforcer.check_api_quota("user-1", plan)

        assert allowed is False
        assert "Daily API limit" in reason

    async def test_reuses_existing_session_for_api_quota_check(self):
        from app.services.billing.quota_enforcer import QuotaEnforcer

        plan = _make_plan(max_api_requests_per_hour=100)

        session = _mock_session()
        record = MagicMock()
        record.api_requests = 1
        result = MagicMock()
        result.scalar_one_or_none.return_value = record
        session.execute = AsyncMock(return_value=result)

        with patch("app.services.billing.quota_enforcer.async_session_maker", side_effect=AssertionError("unexpected new session")):
            enforcer = QuotaEnforcer()
            allowed, reason = await enforcer.check_api_quota("user-1", plan, session=session)

        assert allowed is True
        assert reason == ""


@pytest.mark.asyncio
class TestCheckStorageQuota:
    async def test_allowed_under_limit(self):
        from app.services.billing.quota_enforcer import QuotaEnforcer

        plan = _make_plan(max_storage_mb=500)

        session = _mock_session()
        record = MagicMock()
        record.storage_used_mb = 200
        result = MagicMock()
        result.scalar_one_or_none.return_value = record
        session.execute = AsyncMock(return_value=result)

        with patch("app.services.billing.quota_enforcer.async_session_maker", return_value=session):
            enforcer = QuotaEnforcer()
            allowed, _reason = await enforcer.check_storage_quota("user-1", plan)

        assert allowed is True

    async def test_blocked_at_limit(self):
        from app.services.billing.quota_enforcer import QuotaEnforcer

        plan = _make_plan(max_storage_mb=500)

        session = _mock_session()
        record = MagicMock()
        record.storage_used_mb = 500
        result = MagicMock()
        result.scalar_one_or_none.return_value = record
        session.execute = AsyncMock(return_value=result)

        with patch("app.services.billing.quota_enforcer.async_session_maker", return_value=session):
            enforcer = QuotaEnforcer()
            allowed, reason = await enforcer.check_storage_quota("user-1", plan)

        assert allowed is False
        assert "Storage limit" in reason


@pytest.mark.asyncio
class TestSecondsUntilApiReset:
    async def test_returns_positive_integer(self):
        from app.services.billing.quota_enforcer import QuotaEnforcer

        enforcer = QuotaEnforcer()
        seconds = await enforcer.seconds_until_api_reset()
        assert isinstance(seconds, int)
        assert 1 <= seconds <= 3600
