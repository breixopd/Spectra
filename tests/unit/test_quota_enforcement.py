"""Unit tests for QuotaService (app/services/billing/quota_enforcement.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services.billing.quota_enforcement import _FREE_LIMITS, QuotaService


def _mock_plan(
    *,
    display_name: str = "Pro",
    max_missions_per_month: int | None = 10,
    max_api_requests_per_day: int | None = 500,
    max_api_requests_per_hour: int | None = 50,
) -> MagicMock:
    plan = MagicMock()
    plan.display_name = display_name
    plan.max_missions_per_month = max_missions_per_month
    plan.max_api_requests_per_day = max_api_requests_per_day
    plan.max_api_requests_per_hour = max_api_requests_per_hour
    return plan


def _mock_usage(*, missions_started: int = 0, api_requests: int = 0) -> MagicMock:
    rec = MagicMock()
    rec.missions_started = missions_started
    rec.api_requests = api_requests
    return rec


class TestCheckMissionQuota:
    @pytest.mark.asyncio
    async def test_passes_when_under_limit(self):
        plan = _mock_plan(max_missions_per_month=5)
        usage = _mock_usage(missions_started=2)
        db = AsyncMock()

        with (
            patch(
                "app.services.billing.quota_enforcement._get_user_plan",
                return_value=plan,
            ),
            patch(
                "app.services.billing.quota_enforcement._get_usage",
                return_value=usage,
            ),
        ):
            # Should not raise
            await QuotaService.check_mission_quota("user-1", db)

    @pytest.mark.asyncio
    async def test_raises_429_when_at_limit(self):
        plan = _mock_plan(max_missions_per_month=5)
        usage = _mock_usage(missions_started=5)
        db = AsyncMock()

        with (
            patch(
                "app.services.billing.quota_enforcement._get_user_plan",
                return_value=plan,
            ),
            patch(
                "app.services.billing.quota_enforcement._get_usage",
                return_value=usage,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await QuotaService.check_mission_quota("user-1", db)
            assert exc_info.value.status_code == 429
            assert "Mission quota exceeded" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_raises_429_when_over_limit(self):
        plan = _mock_plan(max_missions_per_month=3)
        usage = _mock_usage(missions_started=7)
        db = AsyncMock()

        with (
            patch(
                "app.services.billing.quota_enforcement._get_user_plan",
                return_value=plan,
            ),
            patch(
                "app.services.billing.quota_enforcement._get_usage",
                return_value=usage,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await QuotaService.check_mission_quota("user-1", db)
            assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_unlimited_plan_always_passes(self):
        plan = _mock_plan(max_missions_per_month=None)
        db = AsyncMock()

        with patch(
            "app.services.billing.quota_enforcement._get_user_plan",
            return_value=plan,
        ):
            # _get_usage should never be called for unlimited
            await QuotaService.check_mission_quota("user-1", db)

    @pytest.mark.asyncio
    async def test_free_tier_defaults_when_no_plan(self):
        usage = _mock_usage(missions_started=0)
        db = AsyncMock()

        with (
            patch(
                "app.services.billing.quota_enforcement._get_user_plan",
                return_value=None,
            ),
            patch(
                "app.services.billing.quota_enforcement._get_usage",
                return_value=usage,
            ),
        ):
            # Under free limit (3) — should pass
            await QuotaService.check_mission_quota("user-1", db)

    @pytest.mark.asyncio
    async def test_free_tier_blocks_at_limit(self):
        usage = _mock_usage(missions_started=_FREE_LIMITS["max_missions_per_month"])
        db = AsyncMock()

        with (
            patch(
                "app.services.billing.quota_enforcement._get_user_plan",
                return_value=None,
            ),
            patch(
                "app.services.billing.quota_enforcement._get_usage",
                return_value=usage,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await QuotaService.check_mission_quota("user-1", db)
            assert exc_info.value.status_code == 429
            assert "Free" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_zero_usage_passes(self):
        plan = _mock_plan(max_missions_per_month=5)
        db = AsyncMock()

        with (
            patch(
                "app.services.billing.quota_enforcement._get_user_plan",
                return_value=plan,
            ),
            patch(
                "app.services.billing.quota_enforcement._get_usage",
                return_value=None,
            ),
        ):
            await QuotaService.check_mission_quota("user-1", db)


class TestCheckApiQuota:
    @pytest.mark.asyncio
    async def test_passes_when_under_daily_limit(self):
        plan = _mock_plan(max_api_requests_per_day=100)
        usage = _mock_usage(api_requests=50)
        db = AsyncMock()

        with (
            patch(
                "app.services.billing.quota_enforcement._get_user_plan",
                return_value=plan,
            ),
            patch(
                "app.services.billing.quota_enforcement._get_usage",
                return_value=usage,
            ),
        ):
            await QuotaService.check_api_quota("user-1", db)

    @pytest.mark.asyncio
    async def test_blocks_when_at_daily_limit(self):
        plan = _mock_plan(max_api_requests_per_day=100)
        usage = _mock_usage(api_requests=100)
        db = AsyncMock()

        with (
            patch(
                "app.services.billing.quota_enforcement._get_user_plan",
                return_value=plan,
            ),
            patch(
                "app.services.billing.quota_enforcement._get_usage",
                return_value=usage,
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await QuotaService.check_api_quota("user-1", db)
            assert exc_info.value.status_code == 429
            assert "API quota exceeded" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_unlimited_api_always_passes(self):
        plan = _mock_plan(max_api_requests_per_day=None)
        db = AsyncMock()

        with patch(
            "app.services.billing.quota_enforcement._get_user_plan",
            return_value=plan,
        ):
            await QuotaService.check_api_quota("user-1", db)


class TestGetUsageSummary:
    @pytest.mark.asyncio
    async def test_returns_correct_structure(self):
        plan = _mock_plan(
            display_name="Team",
            max_missions_per_month=20,
            max_api_requests_per_day=1000,
            max_api_requests_per_hour=100,
        )
        monthly = _mock_usage(missions_started=5)
        daily = _mock_usage(api_requests=42)
        hourly = _mock_usage(api_requests=8)
        db = AsyncMock()

        call_count = 0

        async def _usage_side_effect(uid, period_type, period_start, session):
            nonlocal call_count
            call_count += 1
            if period_type == "monthly":
                return monthly
            if period_type == "daily":
                return daily
            return hourly

        with (
            patch(
                "app.services.billing.quota_enforcement._get_user_plan",
                return_value=plan,
            ),
            patch(
                "app.services.billing.quota_enforcement._get_usage",
                side_effect=_usage_side_effect,
            ),
        ):
            result = await QuotaService.get_usage_summary("user-1", db)

        assert result["plan"] == "Team"
        assert result["missions"]["used"] == 5
        assert result["missions"]["limit"] == 20
        assert result["missions"]["remaining"] == 15
        assert result["api_calls_daily"]["used"] == 42
        assert result["api_calls_hourly"]["used"] == 8
        assert "period" in result
        assert "month_start" in result["period"]
        assert "day_start" in result["period"]

    @pytest.mark.asyncio
    async def test_returns_free_plan_when_no_subscription(self):
        db = AsyncMock()

        with (
            patch(
                "app.services.billing.quota_enforcement._get_user_plan",
                return_value=None,
            ),
            patch(
                "app.services.billing.quota_enforcement._get_usage",
                return_value=None,
            ),
        ):
            result = await QuotaService.get_usage_summary("user-1", db)

        assert result["plan"] == "Free"
        assert result["missions"]["limit"] == _FREE_LIMITS["max_missions_per_month"]
        assert result["missions"]["used"] == 0

    @pytest.mark.asyncio
    async def test_unlimited_plan_fields(self):
        plan = _mock_plan(
            display_name="Enterprise",
            max_missions_per_month=None,
            max_api_requests_per_day=None,
            max_api_requests_per_hour=None,
        )
        db = AsyncMock()

        with (
            patch(
                "app.services.billing.quota_enforcement._get_user_plan",
                return_value=plan,
            ),
            patch(
                "app.services.billing.quota_enforcement._get_usage",
                return_value=None,
            ),
        ):
            result = await QuotaService.get_usage_summary("user-1", db)

        assert result["plan"] == "Enterprise"
        assert result["missions"]["limit"] is None
        assert result["missions"]["remaining"] is None
