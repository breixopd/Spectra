"""Quota enforcement against plan limits."""

from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_maker


@contextlib.asynccontextmanager
async def _use_or_create_session(existing: AsyncSession | None = None):
    """Yield *existing* if provided, otherwise open a new session."""
    if existing is not None:
        yield existing
    else:
        async with async_session_maker() as session:
            yield session
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


def _period_start_daily() -> datetime:
    now = datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _period_start_weekly() -> datetime:
    now = datetime.now(UTC)
    # Start of ISO week (Monday)
    monday = now - __import__("datetime").timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


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

    async def check_mission_quota(
        self, user_id: str, plan: Plan | None = None, *, session: AsyncSession | None = None,
    ) -> tuple[bool, str]:
        """Check if user can start a new mission.

        Returns (allowed, reason).  When *session* is provided the caller's
        transaction is reused so that an advisory lock held by the caller
        remains effective across the quota check and the subsequent write.
        """
        if await self._is_quota_exempt_user(user_id):
            return True, ""
        if plan is None:
            plan = await self._get_plan(user_id)
        if plan is None:
            return False, "No active subscription"

        async with _use_or_create_session(session) as db:
            from app.models.mission import Mission as MissionModel

            # Advisory lock prevents TOCTOU between quota check and mission INSERT
            await db.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": hash(f"mission_quota_{user_id}") & 0x7FFFFFFF},
            )

            locked_sub = await db.execute(
                select(Subscription)
                .where(Subscription.user_id == user_id, Subscription.status == "active")
                .with_for_update()
            )
            locked_sub.scalar_one_or_none()  # acquire lock; discard result

            active_count_result = await db.execute(
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
                rec_result = await db.execute(
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

            # Check daily mission cap
            daily_limit = getattr(plan, "max_missions_per_day", 0)
            if isinstance(daily_limit, int) and daily_limit > 0:
                period = _period_start_daily()
                rec_result = await db.execute(
                    select(UsageRecord).where(
                        UsageRecord.user_id == user_id,
                        UsageRecord.period_type == "daily",
                        UsageRecord.period_start == period,
                    )
                )
                record = rec_result.scalar_one_or_none()
                started = record.missions_started if record else 0
                if started >= daily_limit:
                    return False, (f"Daily mission limit reached: {started}/{daily_limit}")

            # Check weekly mission cap
            weekly_limit = getattr(plan, "max_missions_per_week", 0)
            if isinstance(weekly_limit, int) and weekly_limit > 0:
                period = _period_start_weekly()
                rec_result = await db.execute(
                    select(UsageRecord).where(
                        UsageRecord.user_id == user_id,
                        UsageRecord.period_type == "weekly",
                        UsageRecord.period_start == period,
                    )
                )
                record = rec_result.scalar_one_or_none()
                started = record.missions_started if record else 0
                if started >= weekly_limit:
                    return False, (f"Weekly mission limit reached: {started}/{weekly_limit}")

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
            # Storage is tracked in a cumulative record with a sentinel period
            sentinel = datetime(2000, 1, 1, tzinfo=UTC)
            rec_result = await session.execute(
                select(UsageRecord).where(
                    UsageRecord.user_id == user_id,
                    UsageRecord.period_type == "cumulative",
                    UsageRecord.period_start == sentinel,
                )
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
