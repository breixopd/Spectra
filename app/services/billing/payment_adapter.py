"""Abstract payment provider adapter for future billing integrations."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.database import async_session_maker
from app.models.plan import Plan, Subscription

logger = logging.getLogger(__name__)


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

    @abstractmethod
    async def get_customer_portal_url(self, user_id: str) -> str:
        """Returns a portal URL for managing billing."""
        ...


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

    async def get_customer_portal_url(self, user_id: str) -> str:
        return ""


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Stripe adapter (optional — requires `stripe` package)
# ---------------------------------------------------------------------------


class StripePaymentAdapter(PaymentAdapter):
    """Stripe Checkout-based payment adapter. No card data ever touches our servers."""

    def __init__(self) -> None:
        try:
            import stripe as _stripe
        except ImportError as exc:
            raise ImportError(
                "The 'stripe' package is required for Stripe payments. Install it with: pip install stripe"
            ) from exc
        from app.core.config import get_settings

        _settings = get_settings()
        self._stripe = _stripe
        self._stripe.api_key = _settings.STRIPE_SECRET_KEY.get_secret_value() if _settings.STRIPE_SECRET_KEY else ""
        self._webhook_secret = (
            _settings.STRIPE_WEBHOOK_SECRET.get_secret_value() if _settings.STRIPE_WEBHOOK_SECRET else ""
        )

    @property
    def provider_name(self) -> str:
        return "stripe"

    async def create_customer(self, user_id: str, email: str, name: str) -> str:
        loop = asyncio.get_running_loop()
        customer = await loop.run_in_executor(
            None, lambda: self._stripe.Customer.create(email=email, name=name, metadata={"user_id": user_id})
        )
        return customer["id"]

    async def create_subscription(self, customer_id: str, plan_external_id: str) -> dict:
        loop = asyncio.get_running_loop()
        sub = await loop.run_in_executor(
            None, lambda: self._stripe.Subscription.create(customer=customer_id, items=[{"price": plan_external_id}])
        )
        return dict(sub)

    async def cancel_subscription(self, subscription_id: str) -> bool:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, lambda: self._stripe.Subscription.modify(subscription_id, cancel_at_period_end=True)
        )
        return True

    async def get_subscription_status(self, subscription_id: str) -> str:
        loop = asyncio.get_running_loop()
        sub = await loop.run_in_executor(None, lambda: self._stripe.Subscription.retrieve(subscription_id))
        return sub.get("status", "unknown")

    async def create_checkout_session(self, user_id: str, plan_id: str, success_url: str, cancel_url: str) -> str:
        """Create a Stripe Checkout session URL — user is redirected to Stripe."""
        async with async_session_maker() as session:
            plan = (await session.execute(select(Plan).where(Plan.id == plan_id))).scalar_one_or_none()
            if not plan or not plan.stripe_price_id:
                raise ValueError("Plan has no Stripe price configured")

        loop = asyncio.get_running_loop()
        checkout = await loop.run_in_executor(
            None,
            lambda: self._stripe.checkout.Session.create(
                mode="subscription",
                line_items=[{"price": plan.stripe_price_id, "quantity": 1}],
                success_url=success_url,
                cancel_url=cancel_url,
                client_reference_id=user_id,
                metadata={"plan_id": plan_id, "user_id": user_id},
            ),
        )
        return checkout.url

    async def handle_webhook(self, payload: bytes, signature: str) -> dict:
        """Verify and parse a Stripe webhook event."""
        loop = asyncio.get_running_loop()
        event = await loop.run_in_executor(
            None, lambda: self._stripe.Webhook.construct_event(payload, signature, self._webhook_secret)
        )
        return {"type": event["type"], "data": event["data"]["object"]}

    async def get_customer_portal_url(self, user_id: str) -> str:
        """Get Stripe Customer Portal URL for managing billing."""
        async with async_session_maker() as session:
            sub = (
                await session.execute(
                    select(Subscription).where(
                        Subscription.user_id == user_id,
                        Subscription.status == "active",
                    )
                )
            ).scalar_one_or_none()

        if not sub or not sub.external_customer_id:
            raise ValueError("No active subscription with billing info found")

        from app.core.config import get_settings

        base_url = get_settings().PLATFORM_BASE_URL or "http://localhost:5000"
        loop = asyncio.get_running_loop()
        portal = await loop.run_in_executor(
            None,
            lambda: self._stripe.billing_portal.Session.create(
                customer=sub.external_customer_id,
                return_url=f"{base_url}/profile?section=plan",
            ),
        )
        return portal.url


class CryptoPaymentAdapter(PaymentAdapter):
    """Cryptocurrency payment adapter.

    Supports payment via BTCPay Server, Coinbase Commerce, or similar.
    Admin configures the provider URL and API key in settings.
    """

    def __init__(self) -> None:
        from app.core.config import get_settings

        _settings = get_settings()
        self._provider_url = _settings.CRYPTO_PAYMENT_URL
        self._api_key = _settings.CRYPTO_PAYMENT_API_KEY.get_secret_value() if _settings.CRYPTO_PAYMENT_API_KEY else ""

    @property
    def provider_name(self) -> str:
        return "crypto"

    async def create_customer(self, user_id: str, email: str, name: str) -> str:
        return ""  # Crypto doesn't have persistent customers

    async def create_subscription(self, customer_id: str, plan_external_id: str) -> dict:
        return {}  # No recurring billing in crypto

    async def create_checkout_session(self, user_id: str, plan_id: str, success_url: str, cancel_url: str) -> str:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._provider_url}/api/v1/invoices",
                headers={"Authorization": f"token {self._api_key}"},
                json={
                    "metadata": {"user_id": user_id, "plan_id": plan_id},
                    "checkout": {"redirectURL": success_url},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("checkoutLink", data.get("url", ""))

    async def handle_webhook(self, payload: bytes, signature: str) -> dict:
        import hashlib
        import hmac
        import json

        expected = hmac.new(self._api_key.encode(), payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError("Invalid webhook signature")
        data = json.loads(payload)
        return {"type": data.get("type", ""), "data": data}

    async def get_customer_portal_url(self, user_id: str) -> str:
        return ""  # Crypto doesn't have customer portals

    async def cancel_subscription(self, subscription_id: str) -> bool:
        return True  # No recurring billing in crypto

    async def get_subscription_status(self, subscription_id: str) -> str:
        return "active"  # Admin manages manually


class ManualPaymentAdapter(PaymentAdapter):
    """Manual billing — admin assigns plans directly. No payment processing.

    Useful for: bank transfers, invoices, enterprise contracts,
    or any custom billing arrangement.
    """

    @property
    def provider_name(self) -> str:
        return "manual"

    async def create_customer(self, user_id: str, email: str, name: str) -> str:
        return ""

    async def create_subscription(self, customer_id: str, plan_external_id: str) -> dict:
        return {}

    async def create_checkout_session(self, user_id: str, plan_id: str, success_url: str, cancel_url: str) -> str:
        # No checkout — admin assigns plan directly via admin panel
        return ""

    async def handle_webhook(self, payload: bytes, signature: str) -> dict:
        return {}

    async def get_customer_portal_url(self, user_id: str) -> str:
        return ""

    async def cancel_subscription(self, subscription_id: str) -> bool:
        return True

    async def get_subscription_status(self, subscription_id: str) -> str:
        return "active"


_ADAPTERS: dict[str, type[PaymentAdapter]] = {
    "noop": NoopPaymentAdapter,
    "stripe": StripePaymentAdapter,
    "crypto": CryptoPaymentAdapter,
    "manual": ManualPaymentAdapter,
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

    def __init__(self, adapter: PaymentAdapter | None = None) -> None:
        if adapter is not None:
            self._adapter = adapter
        else:
            from app.core.config import get_settings

            provider = get_settings().PAYMENT_PROVIDER
            adapter_cls = _ADAPTERS.get(provider, NoopPaymentAdapter)
            self._adapter = adapter_cls()

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

    async def get_portal_url(self, user_id: str) -> str:
        """Get billing portal URL for the user."""
        return await self._adapter.get_customer_portal_url(user_id)

    async def create_checkout(self, user_id: str, plan_id: str) -> str:
        """Create a checkout session and return the URL."""
        from app.core.config import get_settings

        base_url = get_settings().PLATFORM_BASE_URL or "http://localhost:5000"
        return await self._adapter.create_checkout_session(
            user_id,
            plan_id,
            success_url=f"{base_url}/profile?section=plan&status=success",
            cancel_url=f"{base_url}/profile?section=plan&status=cancelled",
        )

    async def handle_checkout_completed(
        self,
        user_id: str,
        plan_id: str,
        customer_id: str | None,
        subscription_id: str | None,
    ) -> bool:
        """Process a completed checkout event. Returns True if a new subscription was created."""
        from app.models.user import User as UserModel

        async with async_session_maker() as session:
            # Idempotency check — don't create duplicate subscriptions
            if subscription_id:
                existing = (
                    await session.execute(
                        select(Subscription).where(Subscription.external_subscription_id == subscription_id)
                    )
                ).scalar_one_or_none()
                if existing:
                    return False

            user = (await session.execute(select(UserModel).where(UserModel.id == user_id))).scalar_one_or_none()
            if user:
                user.plan_id = plan_id

            sub = Subscription(
                user_id=user_id,
                plan_id=plan_id,
                status="active",
                external_subscription_id=subscription_id or "",
                external_customer_id=customer_id or "",
                payment_provider="stripe",
            )
            session.add(sub)
            await session.commit()
            return True
