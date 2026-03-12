"""Abstract payment provider adapter for future billing integrations."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.database import async_session_maker
from app.models.plan import Plan, Subscription

logger = logging.getLogger("spectra.billing.payment")


# ---------------------------------------------------------------------------
# Adapter interface
# ---------------------------------------------------------------------------


class PaymentAdapter(ABC):
    """Strategy interface for payment providers (Stripe, crypto, etc.)."""

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @abstractmethod
    async def create_customer(self, user_id: str, email: str, name: str) -> str:
        """Register a customer with the external provider. Returns external customer ID."""
        ...

    @abstractmethod
    async def create_subscription(self, customer_id: str, plan_external_id: str) -> dict:
        """Create a subscription. Returns provider-specific subscription data."""
        ...

    @abstractmethod
    async def cancel_subscription(self, subscription_id: str) -> bool: ...

    @abstractmethod
    async def get_subscription_status(self, subscription_id: str) -> str: ...

    @abstractmethod
    async def create_checkout_session(self, user_id: str, plan_id: str, success_url: str, cancel_url: str) -> str:
        """Returns a checkout URL."""
        ...

    @abstractmethod
    async def handle_webhook(self, payload: bytes, signature: str) -> dict: ...


# ---------------------------------------------------------------------------
# Noop adapter (self-hosted / free deployments)
# ---------------------------------------------------------------------------


class NoopPaymentAdapter(PaymentAdapter):
    """Default adapter that does nothing — for self-hosted or free deployments."""

    @property
    def provider_name(self) -> str:
        return "noop"

    async def create_customer(self, user_id: str, email: str, name: str) -> str:
        return ""

    async def create_subscription(self, customer_id: str, plan_external_id: str) -> dict:
        return {}

    async def cancel_subscription(self, subscription_id: str) -> bool:
        return True

    async def get_subscription_status(self, subscription_id: str) -> str:
        return "active"

    async def create_checkout_session(self, user_id: str, plan_id: str, success_url: str, cancel_url: str) -> str:
        return ""

    async def handle_webhook(self, payload: bytes, signature: str) -> dict:
        return {}


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_ADAPTERS: dict[str, type[PaymentAdapter]] = {
    "noop": NoopPaymentAdapter,
}


def get_payment_adapter(provider: str = "noop") -> PaymentAdapter:
    """Get payment adapter by provider name. Extensible for future providers."""
    cls = _ADAPTERS.get(provider)
    if cls is None:
        raise ValueError(f"Unknown payment provider: {provider!r}")
    return cls()


# ---------------------------------------------------------------------------
# Payment service (orchestrator)
# ---------------------------------------------------------------------------


class PaymentService:
    """Orchestrates subscription lifecycle through a pluggable payment adapter."""

    def __init__(self, adapter: PaymentAdapter) -> None:
        self._adapter = adapter

    async def subscribe_user(self, user_id: str, plan_id: str) -> Subscription:
        """Create or update a user's subscription to the given plan."""
        async with async_session_maker() as session:
            plan = await session.get(Plan, plan_id)
            if plan is None:
                raise ValueError(f"Plan {plan_id!r} not found")

            result = await session.execute(select(Subscription).where(Subscription.user_id == user_id))
            sub = result.scalar_one_or_none()

            now = datetime.now(UTC)

            if sub is None:
                sub = Subscription(
                    user_id=user_id,
                    plan_id=plan_id,
                    status="active",
                    payment_provider=self._adapter.provider_name,
                    current_period_start=now,
                )
                session.add(sub)
            else:
                sub.plan_id = plan_id
                sub.status = "active"
                sub.payment_provider = self._adapter.provider_name
                sub.current_period_start = now

            await session.commit()
            await session.refresh(sub)
            return sub

    async def cancel_user_subscription(self, user_id: str) -> bool:
        """Cancel the user's active subscription."""
        async with async_session_maker() as session:
            result = await session.execute(select(Subscription).where(Subscription.user_id == user_id))
            sub = result.scalar_one_or_none()
            if sub is None:
                return False

            if sub.external_subscription_id:
                await self._adapter.cancel_subscription(sub.external_subscription_id)

            sub.status = "cancelled"
            await session.commit()
            return True

    async def check_subscription_active(self, user_id: str) -> bool:
        """Return True if the user has an active subscription."""
        async with async_session_maker() as session:
            result = await session.execute(
                select(Subscription).where(
                    Subscription.user_id == user_id,
                    Subscription.status == "active",
                )
            )
            return result.scalar_one_or_none() is not None

    async def record_usage(self, user_id: str, metric: str, amount: int) -> None:
        """Delegate to UsageTracker — kept here for convenience."""
        from app.services.billing.usage_tracker import UsageTracker

        tracker = UsageTracker()
        await tracker.record(user_id, metric, amount)

    async def check_usage_limit(self, user_id: str, metric: str) -> tuple[bool, int, int]:
        """Return (within_limit, current_usage, max_allowed)."""
        from app.services.billing.usage_tracker import UsageTracker

        tracker = UsageTracker()
        return await tracker.check_rate_limit(user_id, metric)
