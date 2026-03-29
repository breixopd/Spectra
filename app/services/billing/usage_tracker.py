"""Usage tracking and rate-limit enforcement against plan limits."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.database import async_session_maker
from app.core.telemetry import telemetry
from app.models.plan import Plan, Subscription, UsageRecord

logger = logging.getLogger(__name__)

# Maps metric names to (UsageRecord column, Plan limit column, period_type)
_METRIC_MAP: dict[str, tuple[str, str, str]] = {
    "api_requests": ("api_requests", "max_api_requests_per_hour", "hourly"),
    "missions_started": ("missions_started", "max_missions_per_month", "monthly"),
    "sandbox_minutes": ("sandbox_minutes", "sandbox_max_containers", "monthly"),
    "llm_tokens": ("llm_tokens_used", "max_api_requests_per_day", "daily"),
}


def _period_start(period_type: str) -> datetime:
    """Return the start of the current period for the given type."""
    now = datetime.now(UTC)
    if period_type == "hourly":
        return now.replace(minute=0, second=0, microsecond=0)
    if period_type == "daily":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    # monthly
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class UsageTracker:
    """Handles usage record creation and limit checking against user plans."""

    # ---- convenience shortcuts ----

    async def record_api_request(self, user_id: str) -> None:
        await self.record(user_id, "api_requests", 1)

    async def record_mission_start(self, user_id: str) -> None:
        await self.record(user_id, "missions_started", 1)

    async def record_sandbox_minutes(self, user_id: str, minutes: int) -> None:
        await self.record(user_id, "sandbox_minutes", minutes)

    async def record_llm_tokens(self, user_id: str, tokens: int) -> None:
        await self.record(user_id, "llm_tokens", tokens)

    # ---- core ----

    async def record(self, user_id: str, metric: str, amount: int) -> None:
        """Increment *metric* for *user_id* in the current period."""
        mapping = _METRIC_MAP.get(metric)
        if mapping is None:
            raise ValueError(f"Unknown usage metric: {metric!r}")

        col_name, _, period_type = mapping
        period = _period_start(period_type)

        async with async_session_maker() as session:
            result = await session.execute(
                select(UsageRecord).where(
                    UsageRecord.user_id == user_id,
                    UsageRecord.period_type == period_type,
                    UsageRecord.period_start == period,
                )
            )
            record = result.scalar_one_or_none()

            if record is None:
                record = UsageRecord(
                    user_id=user_id,
                    period_type=period_type,
                    period_start=period,
                )
                session.add(record)

            current = getattr(record, col_name)
            setattr(record, col_name, current + amount)
            await session.commit()

        # Record to telemetry
        telemetry.increment_counter(f"billing.usage.{metric}", amount, {"user_id": user_id, "period": period_type})

    async def check_rate_limit(self, user_id: str, metric: str) -> tuple[bool, int, int]:
        """Return ``(within_limit, current_usage, max_allowed)``.

        If the plan has no limit (``None``), ``max_allowed`` is ``0`` and the
        user is always within the limit.
        """
        mapping = _METRIC_MAP.get(metric)
        if mapping is None:
            raise ValueError(f"Unknown usage metric: {metric!r}")

        col_name, limit_col, period_type = mapping
        period = _period_start(period_type)

        async with async_session_maker() as session:
            # Fetch subscription + plan
            sub_result = await session.execute(select(Subscription).where(Subscription.user_id == user_id))
            sub = sub_result.scalar_one_or_none()
            if sub is None:
                return (False, 0, 0)

            plan = await session.get(Plan, sub.plan_id)
            if plan is None:
                return (False, 0, 0)

            max_allowed: int | None = getattr(plan, limit_col, None)

            # Fetch current usage
            rec_result = await session.execute(
                select(UsageRecord).where(
                    UsageRecord.user_id == user_id,
                    UsageRecord.period_type == period_type,
                    UsageRecord.period_start == period,
                )
            )
            record = rec_result.scalar_one_or_none()
            current = getattr(record, col_name, 0) if record else 0

            if max_allowed is None:
                return (True, current, 0)

            # Record usage level to telemetry
            telemetry.set_gauge(
                f"billing.usage_level.{metric}",
                current / max_allowed * 100 if max_allowed else 0,
                {"user_id": user_id},
            )

            return (current < max_allowed, current, max_allowed)

    async def reset_daily_counters(self) -> None:
        """Reset daily usage counters for all users."""
        try:
            async with async_session_maker() as session:
                from sqlalchemy import update

                stmt = update(UsageRecord).where(
                    UsageRecord.period_type == "daily"
                ).values(
                    api_requests=0,
                    missions_started=0,
                    sandbox_minutes=0,
                    llm_tokens_used=0,
                )
                await session.execute(stmt)
                await session.commit()
        except Exception as e:
            logger.error("Failed to reset daily counters: %s", e)
