"""Self-service billing — plan upgrade/downgrade via Stripe Checkout."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_active_user
from app.core.database import get_async_session
from app.models.plan import Plan
from app.models.user import User
from app.services.billing import PaymentService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["Billing"])


@router.get("/plans")
async def list_available_plans(session: AsyncSession = Depends(get_async_session)):
    """List all active plans available for subscription."""
    plans = (
        await session.execute(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order))
    ).scalars().all()
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
        }
        for p in plans
    ]


@router.post("/checkout")
async def create_checkout(
    plan_id: str,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Create a Stripe Checkout session to subscribe to a plan."""
    plan = (await session.execute(select(Plan).where(Plan.id == plan_id))).scalar_one_or_none()
    if not plan:
        raise HTTPException(404, "Plan not found")

    svc = PaymentService()
    try:
        checkout_url = await svc.create_checkout(str(user.id), str(plan.id))
        return {"checkout_url": checkout_url}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:
        logger.exception("Payment checkout error")
        raise HTTPException(502, "Payment provider error")


@router.get("/portal")
async def get_billing_portal(
    user: User = Depends(get_current_active_user),
):
    """Get Stripe Customer Portal URL for managing billing."""
    svc = PaymentService()
    try:
        url = await svc.get_portal_url(str(user.id))
        return {"portal_url": url}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events (checkout.session.completed, etc.)."""
    from app.core.config import get_settings

    _settings = get_settings()
    if _settings.PAYMENT_PROVIDER != "stripe":
        raise HTTPException(404, "Payment webhooks not enabled")

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    svc = PaymentService()
    try:
        event = await svc._adapter.handle_webhook(payload, sig)
    except Exception:
        logger.exception("Webhook verification failed")
        raise HTTPException(400, "Webhook verification failed")

    event_type = event.get("type", "")
    data = event.get("data", {})

    if event_type == "checkout.session.completed":
        user_id = data.get("client_reference_id") or data.get("metadata", {}).get("user_id")
        plan_id = data.get("metadata", {}).get("plan_id")
        customer_id = data.get("customer")
        subscription_id = data.get("subscription")

        if user_id and plan_id:
            from app.core.database import async_session_maker
            from app.models.plan import Subscription

            async with async_session_maker() as session:
                # Idempotency check — don't create duplicate subscriptions
                existing = (await session.execute(
                    select(Subscription).where(
                        Subscription.external_subscription_id == subscription_id
                    )
                )).scalar_one_or_none()
                if existing:
                    return {"received": True}

                from app.models.user import User as UserModel

                user = (
                    await session.execute(select(UserModel).where(UserModel.id == user_id))
                ).scalar_one_or_none()
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

    return {"received": True}
