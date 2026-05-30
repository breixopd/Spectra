"""Abstract payment provider adapter for future billing integrations."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime

from sqlalchemy import select

from spectra_billing.entitlements import (
    BILLING_PORTAL_MANAGEABLE_SUBSCRIPTION_STATUSES,
    get_user_entitlement,
    subscription_allows_billing_portal,
    subscription_grants_access,
    sync_user_plan_mirror,
)
from spectra_persistence.database import async_session_maker
from spectra_persistence.models.plan import Plan, Subscription

logger = logging.getLogger(__name__)

_STRIPE_TERMINAL_SUBSCRIPTION_STATUSES = frozenset({"cancelled", "incomplete_expired", "unpaid"})


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
        from spectra_common.config import get_settings

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
        await loop.run_in_executor(None, lambda: self._stripe.Subscription.delete(subscription_id))
        return True

    async def get_subscription_status(self, subscription_id: str) -> str:
        loop = asyncio.get_running_loop()
        sub = await loop.run_in_executor(None, lambda: self._stripe.Subscription.retrieve(subscription_id))
        return sub.get("status", "unknown")

    async def create_checkout_session(self, user_id: str, plan_id: str, success_url: str, cancel_url: str) -> str:
        """Create a Stripe Checkout session URL — user is redirected to Stripe."""
        async with async_session_maker() as session:
            plan = (await session.execute(select(Plan).where(Plan.id == plan_id))).scalar_one_or_none()
            if not plan or not plan.is_active or not plan.stripe_price_id:
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
        return {"type": event["type"], "data": event["data"]["object"], "id": event.get("id")}

    async def get_customer_portal_url(self, user_id: str) -> str:
        """Get Stripe Customer Portal URL for managing billing."""
        async with async_session_maker() as session:
            sub = (
                await session.execute(
                    select(Subscription).where(
                        Subscription.payment_provider == "stripe",
                        Subscription.user_id == user_id,
                        Subscription.external_customer_id.is_not(None),
                        Subscription.status.in_(tuple(BILLING_PORTAL_MANAGEABLE_SUBSCRIPTION_STATUSES)),
                    )
                )
            ).scalar_one_or_none()

        if not sub or not sub.external_customer_id:
            raise ValueError("No manageable subscription with billing info found")

        from spectra_common.config import get_settings

        base_url = get_settings().PLATFORM_BASE_URL or "http://localhost:5000"
        if not get_settings().PLATFORM_BASE_URL:
            logger.warning("PLATFORM_BASE_URL not set — using localhost fallback for billing portal")
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
        from spectra_common.config import get_settings

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


def register_payment_adapter(provider: str, adapter_cls: type[PaymentAdapter]) -> None:
    """Register a payment provider adapter.

    Provider packages can call this during startup/import to add a new checkout
    backend without changing PaymentService.
    """
    provider_id = provider.strip().lower()
    if not provider_id:
        raise ValueError("Payment provider id cannot be empty")
    if provider_id in _ADAPTERS:
        raise ValueError(f"Payment provider already registered: {provider_id!r}")
    if not issubclass(adapter_cls, PaymentAdapter):
        raise TypeError("adapter_cls must implement PaymentAdapter")
    _ADAPTERS[provider_id] = adapter_cls


def list_payment_providers() -> list[str]:
    """Return registered payment provider ids."""
    return sorted(_ADAPTERS)


def get_payment_adapter(provider: str = "manual") -> PaymentAdapter:
    """Get payment adapter by provider name. Extensible for future providers."""
    cls = _ADAPTERS.get(provider.strip().lower())
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
            from spectra_common.config import get_settings

            provider = get_settings().PAYMENT_PROVIDER
            adapter_cls = _ADAPTERS.get(provider, ManualPaymentAdapter)
            self._adapter = adapter_cls()

    @staticmethod
    def _normalize_subscription_status(status: str | None) -> str:
        """Normalize provider subscription statuses into the local representation."""
        normalized = (status or "").strip().lower()
        if normalized == "canceled":
            return "cancelled"
        return normalized or "active"

    @staticmethod
    def _stripe_timestamp_to_datetime(value: object) -> datetime | None:
        """Convert a Stripe UNIX timestamp to a timezone-aware datetime."""
        if not isinstance(value, (int, float)):
            return None
        return datetime.fromtimestamp(value, tz=UTC)

    async def _find_local_subscription(
        self,
        session,
        *,
        user_id: str | None = None,
        external_subscription_id: str | None = None,
        external_customer_id: str | None = None,
    ) -> Subscription | None:
        if external_subscription_id:
            existing = (
                await session.execute(
                    select(Subscription).where(Subscription.external_subscription_id == external_subscription_id)
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing

        if user_id:
            existing = (
                await session.execute(select(Subscription).where(Subscription.user_id == user_id))
            ).scalar_one_or_none()
            if existing is not None:
                return existing

        if external_customer_id:
            return (
                await session.execute(
                    select(Subscription).where(Subscription.external_customer_id == external_customer_id)
                )
            ).scalar_one_or_none()

        return None

    async def _find_plan_by_stripe_price_id(self, session, price_id: str | None) -> Plan | None:
        if not price_id:
            return None
        return (
            await session.execute(
                select(Plan).where(
                    Plan.stripe_price_id == price_id,
                    Plan.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()

    async def _get_plan_for_local_state(self, session, *, plan_id: str, normalized_status: str) -> Plan | None:
        plan = await session.get(Plan, plan_id)
        if plan is None:
            raise ValueError(f"Plan {plan_id!r} not found")
        if subscription_grants_access(normalized_status) and not plan.is_active:
            logger.warning("Skipping entitlement-bearing subscription sync for inactive plan %s", plan_id)
            return None
        return plan

    @staticmethod
    def is_stripe_authoritative_subscription(subscription: Subscription | None) -> bool:
        if subscription is None:
            return False
        payment_provider = (subscription.payment_provider or "").strip().lower()
        return payment_provider == "stripe" or bool(
            subscription.external_subscription_id or subscription.external_customer_id
        )

    @staticmethod
    def _get_subscription_provider(subscription: Subscription) -> str | None:
        if subscription.external_subscription_id or subscription.external_customer_id:
            return "stripe"
        payment_provider = (subscription.payment_provider or "").strip().lower()
        if payment_provider:
            return payment_provider
        return None

    async def cancel_external_subscription(self, subscription: Subscription) -> bool:
        external_subscription_id = (subscription.external_subscription_id or "").strip()
        if not external_subscription_id:
            return False

        provider_name = self._get_subscription_provider(subscription)
        if not provider_name:
            return False

        adapter = self._adapter if self._adapter.provider_name == provider_name else get_payment_adapter(provider_name)
        return await adapter.cancel_subscription(external_subscription_id)

    async def _stripe_event_can_mutate_subscription(
        self,
        session,
        *,
        user_id: str | None,
        existing: Subscription | None,
    ) -> bool:
        if existing is not None:
            return True
        if not user_id:
            return True

        current = await self._find_local_subscription(session, user_id=user_id)
        if current is None:
            return True
        return self.is_stripe_authoritative_subscription(current)

    async def _set_local_subscription_state(
        self,
        *,
        user_id: str,
        plan_id: str | None,
        status: str,
        payment_provider: str | None = None,
        external_subscription_id: str | None = None,
        external_customer_id: str | None = None,
        current_period_start: datetime | None = None,
        current_period_end: datetime | None = None,
        metadata: dict | None = None,
    ) -> tuple[Subscription | None, bool]:
        """Create or update the local subscription row and sync the user plan mirror."""
        async with async_session_maker() as session:
            existing = await self._find_local_subscription(
                session,
                user_id=user_id,
                external_subscription_id=external_subscription_id,
                external_customer_id=external_customer_id,
            )
            normalized_status = self._normalize_subscription_status(status)

            if plan_id is not None:
                plan = await self._get_plan_for_local_state(
                    session,
                    plan_id=plan_id,
                    normalized_status=normalized_status,
                )
                if plan is None:
                    return None, False
            elif existing is None:
                return None, False

            created = False
            provider_name = payment_provider or (existing.payment_provider if existing else self._adapter.provider_name)

            if existing is None:
                created = True
                subscription = Subscription(
                    user_id=user_id,
                    plan_id=plan_id,
                    status=normalized_status,
                    payment_provider=provider_name,
                    current_period_start=current_period_start or datetime.now(UTC),
                    current_period_end=current_period_end,
                    external_subscription_id=external_subscription_id,
                    external_customer_id=external_customer_id,
                    metadata_=metadata,
                )
                session.add(subscription)
            else:
                subscription = existing
                if plan_id is not None:
                    subscription.plan_id = plan_id
                subscription.status = normalized_status
                if payment_provider is not None or not subscription.payment_provider:
                    subscription.payment_provider = provider_name
                if external_subscription_id:
                    subscription.external_subscription_id = external_subscription_id
                if external_customer_id:
                    subscription.external_customer_id = external_customer_id
                if current_period_start is not None:
                    subscription.current_period_start = current_period_start
                if current_period_end is not None:
                    subscription.current_period_end = current_period_end
                if metadata is not None:
                    subscription.metadata_ = metadata

            await sync_user_plan_mirror(session, user_id=user_id)
            await session.commit()
            await session.refresh(subscription)
            return subscription, created

    async def subscribe_user(self, user_id: str, plan_id: str) -> Subscription:
        """Create or update a user's subscription to the given plan."""
        sub, _created = await self._set_local_subscription_state(
            user_id=user_id,
            plan_id=plan_id,
            status="active",
            payment_provider=self._adapter.provider_name,
            current_period_start=datetime.now(UTC),
        )
        if sub is None:
            raise ValueError(f"Plan {plan_id!r} not found")
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
            sub.current_period_end = datetime.now(UTC)
            await sync_user_plan_mirror(session, user_id=user_id)
            await session.commit()
            return True

    async def check_subscription_active(self, user_id: str) -> bool:
        """Return True if the user has an active subscription."""
        async with async_session_maker() as session:
            return await get_user_entitlement(session, user_id) is not None

    async def record_usage(self, user_id: str, metric: str, amount: int) -> None:
        """Delegate to UsageTracker — kept here for convenience."""
        from spectra_billing.usage_tracker import UsageTracker

        tracker = UsageTracker()
        await tracker.record(user_id, metric, amount)

    async def check_usage_limit(self, user_id: str, metric: str) -> tuple[bool, int, int]:
        """Return (within_limit, current_usage, max_allowed)."""
        from spectra_billing.usage_tracker import UsageTracker

        tracker = UsageTracker()
        return await tracker.check_rate_limit(user_id, metric)

    async def get_portal_url(self, user_id: str) -> str:
        """Get billing portal URL for the user."""
        return await self._adapter.get_customer_portal_url(user_id)

    async def create_checkout(self, user_id: str, plan_id: str) -> str:
        """Create a checkout session and return the URL."""
        from spectra_common.config import get_settings

        base_url = get_settings().PLATFORM_BASE_URL or "http://localhost:5000"
        if not get_settings().PLATFORM_BASE_URL:
            logger.warning("PLATFORM_BASE_URL not set — using localhost fallback for checkout")
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
        """Process a completed checkout event and persist the resulting entitlement state."""
        async with async_session_maker() as session:
            existing = await self._find_local_subscription(
                session,
                external_subscription_id=subscription_id,
                external_customer_id=customer_id,
            )
            if not await self._stripe_event_can_mutate_subscription(session, user_id=user_id, existing=existing):
                return False

        _sub, created = await self._set_local_subscription_state(
            user_id=user_id,
            plan_id=plan_id,
            status="active",
            payment_provider="stripe",
            external_subscription_id=subscription_id,
            external_customer_id=customer_id,
            metadata={"source": "checkout.session.completed"},
        )
        return created

    async def reconcile_stripe_event(self, event_type: str, data: dict) -> bool:
        """Reconcile local entitlement state from Stripe checkout and subscription lifecycle events."""
        if event_type == "checkout.session.completed":
            user_id = data.get("client_reference_id") or data.get("metadata", {}).get("user_id")
            plan_id = data.get("metadata", {}).get("plan_id")
            if not user_id or not plan_id:
                return False
            return await self.handle_checkout_completed(
                user_id=user_id,
                plan_id=plan_id,
                customer_id=data.get("customer"),
                subscription_id=data.get("subscription"),
            )

        if event_type in {"customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}:
            async with async_session_maker() as session:
                existing = await self._find_local_subscription(
                    session,
                    external_subscription_id=data.get("id"),
                    external_customer_id=data.get("customer"),
                )
                metadata = data.get("metadata") or {}
                user_id = metadata.get("user_id") or (str(existing.user_id) if existing is not None else None)
                plan_id = metadata.get("plan_id")

                items = data.get("items", {}).get("data", [])
                price = items[0].get("price") if items and isinstance(items[0], dict) else None
                price_id = price.get("id") if isinstance(price, dict) else None
                plan = await self._find_plan_by_stripe_price_id(session, price_id)
                if plan is not None:
                    plan_id = str(plan.id)
                elif not plan_id and existing is not None:
                    plan_id = str(existing.plan_id)

                if not await self._stripe_event_can_mutate_subscription(session, user_id=user_id, existing=existing):
                    return False

            if not user_id or not plan_id:
                return False

            status = data.get("status") or ("cancelled" if event_type.endswith(".deleted") else "active")
            sub, _created = await self._set_local_subscription_state(
                user_id=user_id,
                plan_id=plan_id,
                status=status,
                payment_provider="stripe",
                external_subscription_id=data.get("id"),
                external_customer_id=data.get("customer"),
                current_period_start=self._stripe_timestamp_to_datetime(data.get("current_period_start")),
                current_period_end=self._stripe_timestamp_to_datetime(data.get("current_period_end")),
                metadata=data.get("metadata") or None,
            )
            return sub is not None

        if event_type in {"invoice.payment_failed", "invoice.payment_succeeded"}:
            async with async_session_maker() as session:
                existing = await self._find_local_subscription(
                    session,
                    external_subscription_id=data.get("subscription"),
                    external_customer_id=data.get("customer"),
                )
                if existing is None:
                    return False
                existing_status = self._normalize_subscription_status(existing.status)
                if existing_status in _STRIPE_TERMINAL_SUBSCRIPTION_STATUSES:
                    return False
                if event_type == "invoice.payment_succeeded" and not (
                    subscription_grants_access(existing.status) or subscription_allows_billing_portal(existing_status)
                ):
                    return False
                user_id = str(existing.user_id)
                plan_id = str(existing.plan_id)
                payment_provider = existing.payment_provider or "stripe"

            status = "past_due" if event_type == "invoice.payment_failed" else "active"
            sub, _created = await self._set_local_subscription_state(
                user_id=user_id,
                plan_id=plan_id,
                status=status,
                payment_provider=payment_provider,
                external_subscription_id=data.get("subscription"),
                external_customer_id=data.get("customer"),
            )
            return sub is not None

        if event_type == "charge.refunded":
            # Webhook `data` is the Charge object: resolve subscription via IDs on the charge.
            customer_id = data.get("customer") if isinstance(data.get("customer"), str) else None
            subscription_id = data.get("subscription") if isinstance(data.get("subscription"), str) else None
            async with async_session_maker() as session:
                existing = await self._find_local_subscription(
                    session,
                    external_subscription_id=subscription_id,
                    external_customer_id=customer_id,
                )
                if existing is None:
                    return False
                existing_status = self._normalize_subscription_status(existing.status)
                if existing_status in _STRIPE_TERMINAL_SUBSCRIPTION_STATUSES:
                    return False
                user_id = str(existing.user_id)
                plan_id = str(existing.plan_id)
                payment_provider = existing.payment_provider or "stripe"
                ext_sub = existing.external_subscription_id
                ext_cus = existing.external_customer_id

            sub, _created = await self._set_local_subscription_state(
                user_id=user_id,
                plan_id=plan_id,
                status="past_due",
                payment_provider=payment_provider,
                external_subscription_id=ext_sub,
                external_customer_id=ext_cus,
            )
            return sub is not None

        return False
