"""Quota enforcement against plan limits."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

UTC = UTC

from sqlalchemy import func, select

from app.core.database import async_session_maker
from app.models.plan import Plan, Subscription, UsageRecord
from app.models.user import User

logger = logging.getLogger(__name__)


def _is_admin_user(user: User | None) -> bool:
    return bool(user and (user.is_superuser or user.role == "admin"))


def _period_start_hourly() -> datetime:
    now = datetime.now(UTC)
    return now.replace(minute=0, second=0, microsecond=0)


def _period_start_monthly() -> datetime:
    now = datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class QuotaEnforcer:
    """Check plan quotas before allowing resource usage."""

    async def _is_quota_exempt_user(self, user_id: str) -> bool:
        async with async_session_maker() as session:
            user = await session.get(User, user_id)
            return _is_admin_user(user)

    async def _get_plan(self, user_id: str) -> Plan | None:
        async with async_session_maker() as session:
            result = await session.execute(
                select(Subscription).where(
                    Subscription.user_id == user_id,
                    Subscription.status == "active",
                )
            )
            sub = result.scalar_one_or_none()
            if sub is None:
                return None
            plan = await session.get(Plan, sub.plan_id)
            return plan

    async def check_mission_quota(self, user_id: str, plan: Plan | None = None) -> tuple[bool, str]:
        """Check if user can start a new mission.

        Returns (allowed, reason).
        """
        if await self._is_quota_exempt_user(user_id):
            return True, ""
        if plan is None:
            plan = await self._get_plan(user_id)
        if plan is None:
            return False, "No active subscription"

        async with async_session_maker() as session:
            # Use a row-level lock on the user's subscription to prevent
            # concurrent requests from both reading the same count and both
            # passing the quota check simultaneously (TOCTOU).
            from app.models.mission import Mission as MissionModel

            locked_sub = await session.execute(
                select(Subscription)
                .where(Subscription.user_id == user_id, Subscription.status == "active")
                .with_for_update()
            )
            locked_sub.scalar_one_or_none()  # acquire lock; discard result

            active_count_result = await session.execute(
                select(func.count(MissionModel.id)).where(
                    MissionModel.user_id == user_id,
                    MissionModel.status.in_(["created", "running", "paused"]),
                )
            )
            active_count = active_count_result.scalar() or 0

            if plan.max_concurrent_missions and active_count >= plan.max_concurrent_missions:
                return False, (f"Concurrent mission limit reached: {active_count}/{plan.max_concurrent_missions}")

            # Check monthly mission cap
            if plan.max_missions_per_month is not None:
                period = _period_start_monthly()
                rec_result = await session.execute(
                    select(UsageRecord).where(
                        UsageRecord.user_id == user_id,
                        UsageRecord.period_type == "monthly",
                        UsageRecord.period_start == period,
                    )
                )
                record = rec_result.scalar_one_or_none()
                started = record.missions_started if record else 0
                if started >= plan.max_missions_per_month:
                    return False, (f"Monthly mission limit reached: {started}/{plan.max_missions_per_month}")

        return True, ""

    async def check_api_quota(self, user_id: str, plan: Plan | None = None) -> tuple[bool, str]:
        """Check if user has API calls remaining this hour.

        Returns (allowed, reason).
        """
        if plan is not None and plan.max_api_requests_per_hour == 0:
            return True, ""
        if await self._is_quota_exempt_user(user_id):
            return True, ""
        if plan is None:
            plan = await self._get_plan(user_id)
        if plan is None:
            return False, "No active subscription"

        if not plan.max_api_requests_per_hour:
            return True, ""

        period = _period_start_hourly()
        async with async_session_maker() as session:
            rec_result = await session.execute(
                select(UsageRecord).where(
                    UsageRecord.user_id == user_id,
                    UsageRecord.period_type == "hourly",
                    UsageRecord.period_start == period,
                )
            )
            record = rec_result.scalar_one_or_none()
            current = record.api_requests if record else 0

            if current >= plan.max_api_requests_per_hour:
                return False, (f"Hourly API limit reached: {current}/{plan.max_api_requests_per_hour}")

        return True, ""

    async def check_storage_quota(self, user_id: str, plan: Plan | None = None) -> tuple[bool, str]:
        """Check if user has storage remaining.

        Returns (allowed, reason).
        """
        if await self._is_quota_exempt_user(user_id):
            return True, ""
        if plan is None:
            plan = await self._get_plan(user_id)
        if plan is None:
            return False, "No active subscription"

        if not plan.max_storage_mb:
            return True, ""

        async with async_session_maker() as session:
            # Get latest usage record with storage data
            rec_result = await session.execute(
                select(UsageRecord)
                .where(UsageRecord.user_id == user_id)
                .order_by(UsageRecord.period_start.desc())
                .limit(1)
            )
            record = rec_result.scalar_one_or_none()
            used = record.storage_used_mb if record else 0

            if used >= plan.max_storage_mb:
                return False, (f"Storage limit reached: {used}/{plan.max_storage_mb} MB")

        return True, ""

    async def seconds_until_api_reset(self) -> int:
        """Seconds until the current hourly window resets."""
        now = datetime.now(UTC)
        next_hour = now.replace(minute=0, second=0, microsecond=0)
        # Move to next hour
        from datetime import timedelta

        next_hour += timedelta(hours=1)
        return max(1, int((next_hour - now).total_seconds()))
