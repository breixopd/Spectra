"""Self-service billing — provider-aware plan browsing and checkout."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_active_user
from app.auth.rate_limit import RateLimits, limiter
from app.core.config import get_settings
from app.core.database import get_async_session
from app.models.plan import Plan, UsageRecord
from app.models.user import User
from app.services.billing import PaymentService
from app.services.billing.entitlements import get_manageable_billing_subscription, get_user_entitlement
from app.services.billing.payment_adapter import get_payment_adapter, list_payment_providers

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["Billing"])

_STRIPE_RECONCILED_EVENT_TYPES = frozenset(
    {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.payment_failed",
        "invoice.payment_succeeded",
    }
)


def _plan_checkout_available(plan: Plan, *, payment_provider: str) -> bool:
    provider_name = (payment_provider or "manual").strip().lower()
    if provider_name == "stripe":
        return bool(plan.stripe_price_id)
    return provider_name == "crypto"


@router.get("/plans")
@limiter.limit(RateLimits.BILLING)
async def list_available_plans(request: Request, session: AsyncSession = Depends(get_async_session)):
    """List all active plans available for subscription."""
    payment_provider = (get_settings().PAYMENT_PROVIDER or "manual").strip().lower()
    plans = (
        (await session.execute(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order))).scalars().all()
    )
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "display_name": p.display_name,
            "description": p.description,
            "features": p.features,
            "max_concurrent_missions": p.max_concurrent_missions,
            "max_missions_per_month": p.max_missions_per_month,
            "max_targets": p.max_targets,
            "max_storage_mb": p.max_storage_mb,
            "stripe_price_id": p.stripe_price_id,
            "checkout_available": _plan_checkout_available(p, payment_provider=payment_provider),
            "checkout_provider": payment_provider,
        }
        for p in plans
    ]


@router.get("/usage")
@limiter.limit(RateLimits.BILLING)
async def get_usage(
    request: Request,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Return the authenticated user's current usage and plan limits."""
    entitlement = await get_user_entitlement(session, str(user.id))
    plan = entitlement.plan if entitlement is not None else None

    # Fetch cumulative storage record
    sentinel = datetime(2000, 1, 1, tzinfo=UTC)
    rec_result = await session.execute(
        select(UsageRecord).where(
            UsageRecord.user_id == str(user.id),
            UsageRecord.period_type == "cumulative",
            UsageRecord.period_start == sentinel,
        )
    )
    record = rec_result.scalar_one_or_none()

    storage_used_mb = record.storage_used_mb if record else 0
    max_storage_mb = plan.max_storage_mb if plan else 0

    return {
        "storage_used_mb": storage_used_mb,
        "max_storage_mb": max_storage_mb,
        "storage_pct": round(storage_used_mb / max_storage_mb * 100, 1) if max_storage_mb else 0,
        "plan_name": plan.display_name if plan else None,
    }


@router.post("/checkout")
@limiter.limit(RateLimits.BILLING)
async def create_checkout(
    request: Request,
    plan_id: str,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Create a provider checkout session to subscribe to a plan."""
    plan = (
        await session.execute(
            select(Plan).where(
                Plan.id == plan_id,
                Plan.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if not plan:
        raise HTTPException(404, "Plan not found")

    payment_provider = (get_settings().PAYMENT_PROVIDER or "manual").strip().lower()
    if not _plan_checkout_available(plan, payment_provider=payment_provider):
        raise HTTPException(400, "Plan is not available for self-service checkout")

    if payment_provider == "stripe":
        manageable_subscription = await get_manageable_billing_subscription(
            session,
            str(user.id),
            provider="stripe",
        )
        if manageable_subscription is not None:
            raise HTTPException(
                409,
                "You already have a Stripe-managed subscription. Use the billing portal to change or recover it.",
            )

    svc = PaymentService()
    try:
        checkout_url = await svc.create_checkout(str(user.id), str(plan.id))
        return {"checkout_url": checkout_url}
    except ValueError:
        logger.exception("Checkout session initialization failed")
        raise HTTPException(400, detail="Failed to initialize checkout session")
    except (OSError, RuntimeError):
        logger.exception("Payment checkout error")
        raise HTTPException(502, "Payment provider error")


@router.get("/portal")
@limiter.limit(RateLimits.BILLING)
async def get_billing_portal(
    request: Request,
    user: User = Depends(get_current_active_user),
):
    """Get Stripe Customer Portal URL for managing billing."""
    svc = PaymentService()
    try:
        url = await svc.get_portal_url(str(user.id))
        return {"portal_url": url}
    except ValueError:
        logger.exception("Billing portal request failed")
        raise HTTPException(400, detail="Failed to process billing portal request")


def _signature_for_provider(request: Request, provider: str) -> str:
    if provider == "stripe":
        return request.headers.get("stripe-signature", "")
    return (
        request.headers.get(f"{provider}-signature")
        or request.headers.get("x-webhook-signature")
        or request.headers.get("x-signature")
        or ""
    )


async def _handle_provider_webhook(request: Request, provider: str):
    provider_id = provider.strip().lower()
    if provider_id not in list_payment_providers():
        raise HTTPException(404, "Payment provider is not registered")

    payload = await request.body()
    sig = _signature_for_provider(request, provider_id)

    adapter = get_payment_adapter(provider_id)
    try:
        event = await adapter.handle_webhook(payload, sig)
    except (OSError, RuntimeError, ValueError):
        logger.exception("Webhook verification failed")
        raise HTTPException(400, "Webhook verification failed")

    event_type = event.get("type", "")
    data = event.get("data", {})

    if provider_id == "stripe" and event_type in _STRIPE_RECONCILED_EVENT_TYPES:
        svc = PaymentService(adapter)
        await svc.reconcile_stripe_event(event_type, data)

    return {"received": True, "provider": provider_id}


@router.post("/webhooks/{provider}")
async def payment_provider_webhook(request: Request, provider: str):
    """Handle provider-scoped payment webhooks."""
    return await _handle_provider_webhook(request, provider)


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events (checkout.session.completed, etc.)."""
    return await _handle_provider_webhook(request, "stripe")
