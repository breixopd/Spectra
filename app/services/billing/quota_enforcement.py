"""Usage quota enforcement for plan limits."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.plan import Plan, Subscription, UsageRecord

logger = logging.getLogger("spectra.billing.quota")

# Free-tier defaults when user has no plan/subscription
_FREE_LIMITS = {
    "max_missions_per_month": 3,
    "max_api_requests_per_day": 100,
    "max_api_requests_per_hour": 20,
}


def _current_month_start() -> datetime:
    return datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _current_day_start() -> datetime:
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


async def _get_user_plan(user_id: str, db: AsyncSession) -> Plan | None:
    """Fetch user's plan via subscription."""
    result = await db.execute(
        select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.status == "active",
        )
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        return None
    return await db.get(Plan, sub.plan_id)


async def _get_usage(user_id: str, period_type: str, period_start: datetime, db: AsyncSession) -> UsageRecord | None:
    result = await db.execute(
        select(UsageRecord).where(
            UsageRecord.user_id == user_id,
            UsageRecord.period_type == period_type,
            UsageRecord.period_start == period_start,
        )
    )
    return result.scalar_one_or_none()


class QuotaService:
    """Enforces plan usage limits."""

    @staticmethod
    async def check_mission_quota(user_id: str, db: AsyncSession) -> None:
        """Verify user hasn't exceeded their plan's mission limit.

        Raises HTTPException(429) if quota exceeded.
        """
        plan = await _get_user_plan(user_id, db)
        limit = plan.max_missions_per_month if plan else _FREE_LIMITS["max_missions_per_month"]

        if limit is None:  # unlimited
            return

        record = await _get_usage(user_id, "monthly", _current_month_start(), db)
        used = record.missions_started if record else 0

        if used >= limit:
            plan_name = plan.display_name if plan else "Free"
            raise HTTPException(
                status_code=429,
                detail=f"Mission quota exceeded. Current plan ({plan_name}) allows {limit} missions/month. Used: {used}.",
                headers={"Retry-After": "86400"},
            )

    @staticmethod
    async def check_api_quota(user_id: str, db: AsyncSession) -> None:
        """Verify user hasn't exceeded API call limit (daily)."""
        plan = await _get_user_plan(user_id, db)
        limit = plan.max_api_requests_per_day if plan else _FREE_LIMITS["max_api_requests_per_day"]

        if limit is None:
            return

        record = await _get_usage(user_id, "daily", _current_day_start(), db)
        used = record.api_requests if record else 0

        if used >= limit:
            plan_name = plan.display_name if plan else "Free"
            raise HTTPException(
                status_code=429,
                detail=f"API quota exceeded. Current plan ({plan_name}) allows {limit} API calls/day. Used: {used}.",
                headers={"Retry-After": "3600"},
            )

    @staticmethod
    async def check_scan_quota(user_id: str, db: AsyncSession) -> None:
        """Verify user hasn't exceeded scan (mission) limit.

        Scans are tracked as missions; this is an alias for mission quota.
        """
        await QuotaService.check_mission_quota(user_id, db)

    @staticmethod
    async def get_usage_summary(user_id: str, db: AsyncSession) -> dict:
        """Get current usage vs limits for display."""
        plan = await _get_user_plan(user_id, db)

        mission_limit = plan.max_missions_per_month if plan else _FREE_LIMITS["max_missions_per_month"]
        api_daily_limit = plan.max_api_requests_per_day if plan else _FREE_LIMITS["max_api_requests_per_day"]
        api_hourly_limit = plan.max_api_requests_per_hour if plan else _FREE_LIMITS["max_api_requests_per_hour"]

        monthly_rec = await _get_usage(user_id, "monthly", _current_month_start(), db)
        daily_rec = await _get_usage(user_id, "daily", _current_day_start(), db)
        hourly_rec = await _get_usage(
            user_id,
            "hourly",
            datetime.now(UTC).replace(minute=0, second=0, microsecond=0),
            db,
        )

        missions_used = monthly_rec.missions_started if monthly_rec else 0
        api_daily_used = daily_rec.api_requests if daily_rec else 0
        api_hourly_used = hourly_rec.api_requests if hourly_rec else 0

        def _build(used: int, limit: int | None) -> dict:
            if limit is None:
                return {"used": used, "limit": None, "remaining": None}
            return {"used": used, "limit": limit, "remaining": max(0, limit - used)}

        return {
            "plan": plan.display_name if plan else "Free",
            "missions": _build(missions_used, mission_limit),
            "api_calls_daily": _build(api_daily_used, api_daily_limit),
            "api_calls_hourly": _build(api_hourly_used, api_hourly_limit),
            "period": {
                "month_start": _current_month_start().isoformat(),
                "day_start": _current_day_start().isoformat(),
            },
        }
