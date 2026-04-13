"""Helpers for deriving the canonical user entitlement from subscriptions."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.plan import Plan, Subscription
from app.models.user import User

ENTITLEMENT_ACTIVE_SUBSCRIPTION_STATUSES = frozenset({"active", "trialing"})
BILLING_PORTAL_MANAGEABLE_SUBSCRIPTION_STATUSES = frozenset({"active", "trialing", "past_due"})


def subscription_grants_access(status: str | None) -> bool:
    """Return True when a subscription status should grant runtime access."""
    if not status:
        return False
    return status.strip().lower() in ENTITLEMENT_ACTIVE_SUBSCRIPTION_STATUSES


def subscription_allows_billing_portal(status: str | None) -> bool:
    """Return True when a subscription should still be manageable in the billing portal."""
    if not status:
        return False
    return status.strip().lower() in BILLING_PORTAL_MANAGEABLE_SUBSCRIPTION_STATUSES


@dataclass(slots=True)
class UserEntitlement:
    """Canonical runtime entitlement derived from the user's active subscription."""

    subscription: Subscription
    plan: Plan


async def get_user_entitlement(session: AsyncSession, user_id: str) -> UserEntitlement | None:
    """Return the user's active subscription-backed entitlement, if any."""
    stmt = (
        select(Subscription, Plan)
        .join(Plan, Plan.id == Subscription.plan_id)
        .where(
            Subscription.user_id == user_id,
            Subscription.status.in_(tuple(ENTITLEMENT_ACTIVE_SUBSCRIPTION_STATUSES)),
            Plan.is_active.is_(True),
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.first()
    if row is None:
        return None
    subscription, plan = row
    return UserEntitlement(subscription=subscription, plan=plan)


async def get_user_entitlement_plan(session: AsyncSession, user_id: str) -> Plan | None:
    """Return the active plan that currently grants the user access."""
    entitlement = await get_user_entitlement(session, user_id)
    if entitlement is None:
        return None
    return entitlement.plan


async def get_manageable_billing_subscription(
    session: AsyncSession,
    user_id: str,
    *,
    provider: str = "stripe",
) -> Subscription | None:
    """Return a subscription that should be managed via the provider billing portal."""
    provider_name = provider.strip().lower()
    stmt = select(Subscription).where(
        Subscription.user_id == user_id,
        Subscription.status.in_(tuple(BILLING_PORTAL_MANAGEABLE_SUBSCRIPTION_STATUSES)),
        Subscription.external_customer_id.is_not(None),
    )
    if provider_name == "stripe":
        stmt = stmt.where(
            or_(
                Subscription.payment_provider == "stripe",
                Subscription.external_subscription_id.is_not(None),
            )
        )
    else:
        stmt = stmt.where(Subscription.payment_provider == provider_name)
    result = await session.execute(stmt.limit(1))
    return result.scalar_one_or_none()


async def sync_user_plan_mirror(
    session: AsyncSession,
    *,
    user: User | None = None,
    user_id: str | None = None,
) -> User | None:
    """Mirror the canonical entitlement plan onto user.plan_id for compatibility."""
    if user is None:
        if not user_id:
            raise ValueError("user or user_id is required")
        user = await session.get(User, user_id)

    if user is None:
        return None

    plan = await get_user_entitlement_plan(session, str(user.id))
    user.plan_id = str(plan.id) if plan is not None else None
    return user