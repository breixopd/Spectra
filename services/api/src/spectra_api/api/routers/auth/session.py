"""Session management, user profile, BYOK (API keys), and activity endpoints."""

import hashlib
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rate_limit import RateLimits, limiter
from app.auth.security import verify_password
from app.core.database import get_async_session
from app.models.audit_log import AuditEventType
from app.models.plan import Plan, Subscription
from app.models.user import User
from app.services.billing.entitlements import get_user_entitlement, subscription_allows_billing_portal
from app.services.system.audit import log_event as audit_log_event
from spectra_api.api.dependencies import _is_admin_user, get_current_active_user
from spectra_api.api.routers.auth._helpers import _clear_auth_cookies
from spectra_api.api.routers.auth.schemas import RestrictProcessingRequest, UpdateProfileRequest
from spectra_api.api.schemas.system import DeleteAccountRequest
from spectra_api.authz import Permission, has_permission

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/me", tags=["Auth"])
@limiter.limit(RateLimits.SESSION_READ)
async def get_current_profile(
    request: Request,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Return current user's profile and plan details."""
    entitlement = await get_user_entitlement(session, str(user.id))
    plan = entitlement.plan if entitlement is not None else None
    subscription_result = await session.execute(
        select(Subscription, Plan.display_name)
        .outerjoin(Plan, Plan.id == Subscription.plan_id)
        .where(Subscription.user_id == str(user.id))
    )
    subscription_row = subscription_result.first()
    subscription = subscription_row[0] if subscription_row is not None else None
    subscription_plan_name = subscription_row[1] if subscription_row is not None else None

    # Check if user has preferences configured
    from app.models.user_preferences import UserPreferences

    prefs_result = await session.execute(select(UserPreferences.id).where(UserPreferences.user_id == str(user.id)))
    has_preferences = prefs_result.scalar_one_or_none() is not None

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_superuser": user.is_superuser,
        "can_access_observability": _is_admin_user(user) or has_permission(user.role, Permission.MANAGE_SETTINGS),
        "mfa_enabled": user.mfa_enabled,
        "processing_restricted": user.processing_restricted,
        "has_preferences": has_preferences,
        "preferences_url": "/api/v1/user/settings",
        "subscription": {
            "status": subscription.status,
            "payment_provider": subscription.payment_provider,
            "plan_id": str(subscription.plan_id) if subscription.plan_id else None,
            "plan_display_name": subscription_plan_name,
            "can_manage_billing": bool(
                subscription.payment_provider == "stripe"
                and subscription.external_customer_id
                and subscription_allows_billing_portal(subscription.status)
            ),
        }
        if subscription
        else None,
        "plan": {
            "id": plan.id,
            "name": plan.name,
            "display_name": plan.display_name,
            "features": plan.features,
            "max_concurrent_missions": plan.max_concurrent_missions,
            "max_missions_per_month": plan.max_missions_per_month,
            "max_targets": plan.max_targets,
            "max_storage_mb": plan.max_storage_mb,
            "max_api_requests_per_hour": plan.max_api_requests_per_hour,
        }
        if plan
        else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.put("/me", tags=["Auth"])
@limiter.limit(RateLimits.PROFILE_UPDATE)
async def update_profile(
    request: Request,
    body: UpdateProfileRequest,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Update current user's profile."""
    if body.email is not None:
        import re

        if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", body.email):
            raise HTTPException(status_code=400, detail="Invalid email format")
        existing = await session.execute(select(User).where(User.email == body.email, User.id != user.id))
        if existing.scalar_one_or_none():
            # Don't reveal whether an email exists — return success silently
            logger.warning("Email change conflict for user=%s target=%s", user.id, body.email)
            return {"detail": "Profile updated"}
        old_email = user.email
        user.email = body.email
        await session.commit()

        try:
            await audit_log_event(
                session,
                AuditEventType.SETTINGS_CHANGED,
                user_id=str(user.id),
                details={"action": "email_changed", "old_email": old_email, "new_email": body.email},
                request=request,
            )
        except (OSError, RuntimeError) as exc:
            logger.warning("Failed to log audit event for email change: %s", exc)
    else:
        await session.commit()
    return {"detail": "Profile updated"}


@router.get("/export-data", tags=["Account"])
@limiter.limit(RateLimits.EXPORT_DATA)
async def export_user_data(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> JSONResponse:
    """Export all user data for GDPR Article 20 compliance."""
    from app.models.audit_log import AuditLog
    from app.models.finding import Finding
    from app.models.mission import Mission
    from app.models.target import Target

    user_id = current_user.id

    profile = {
        "id": str(user_id),
        "username": current_user.username,
        "email": current_user.email,
        "role": current_user.role,
        "is_superuser": current_user.is_superuser,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
        "mfa_enabled": current_user.mfa_enabled,
        "processing_restricted": current_user.processing_restricted,
    }

    result = await session.execute(
        select(Mission).where(Mission.user_id == user_id).order_by(Mission.created_at.desc())
    )
    missions = []
    for m in result.scalars().all():
        missions.append(
            {
                "id": str(m.id),
                "target": m.target,
                "status": m.status,
                "directive": m.directive,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "completed_at": m.completed_at.isoformat() if hasattr(m, "completed_at") and m.completed_at else None,
            }
        )

    result = await session.execute(select(Target).where(Target.user_id == user_id))
    targets = []
    for t in result.scalars().all():
        targets.append(
            {
                "id": str(t.id),
                "address": t.address,
                "hostname": getattr(t, "hostname", None),
                "status": getattr(t, "status", None),
            }
        )

    result = await session.execute(select(Finding).where(Finding.user_id == user_id))
    findings = []
    for f in result.scalars().all():
        findings.append(
            {
                "id": str(f.id),
                "title": f.title,
                "severity": f.severity,
                "description": getattr(f, "description", None),
                "status": getattr(f, "status", None),
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
        )


    result = await session.execute(
        select(AuditLog).where(AuditLog.user_id == user_id).order_by(AuditLog.created_at.desc()).limit(1000)
    )
    audit_entries = []
    for a in result.scalars().all():
        audit_entries.append(
            {
                "event_type": a.event_type,
                "details": a.details,
                "ip_address": a.ip_address,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
        )

    export_data = {
        "export_version": "1.0",
        "exported_at": datetime.now(UTC).isoformat(),
        "user_profile": profile,
        "missions": missions,
        "targets": targets,
        "findings": findings,
        "audit_log": audit_entries,
    }

    return JSONResponse(
        content=export_data,
        headers={
            "Content-Disposition": f'attachment; filename="spectra-data-export-{current_user.username}.json"',
        },
    )


@router.post("/restrict-processing", tags=["Account"])
@limiter.limit(RateLimits.SESSION_WRITE)
async def toggle_restrict_processing(
    request: Request,
    body: RestrictProcessingRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Toggle GDPR Art. 18 restriction-of-processing flag on the user account."""
    current_user.processing_restricted = body.restricted
    await session.commit()

    await audit_log_event(
        session,
        AuditEventType.SETTINGS_CHANGED,
        user_id=str(current_user.id),
        details={"action": "processing_restricted", "value": body.restricted},
        request=request,
    )

    return {"detail": "Processing restriction updated", "processing_restricted": body.restricted}


@router.delete("/account", tags=["Auth"])
@limiter.limit(RateLimits.ACCOUNT_DELETE)
async def delete_account(
    request: Request,
    response: Response,
    body: DeleteAccountRequest,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Permanently delete user account and all associated data."""
    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(400, "Password is incorrect")

    if user.is_superuser:
        stmt = select(func.count()).select_from(User).where(User.is_superuser.is_(True), User.is_active.is_(True))
        result = await session.execute(stmt)
        if result.scalar_one() <= 1:
            raise HTTPException(400, "Cannot delete the last superuser account")

    user_id = str(user.id)
    username = user.username

    await audit_log_event(
        session,
        AuditEventType.ACCOUNT_DELETED,
        user_id=user_id,
        details={"username": username},
        request=request,
    )

    from sqlalchemy import text

    await session.execute(
        text("UPDATE audit_logs SET user_id = NULL WHERE user_id = :uid"),
        {"uid": user_id},
    )

    await session.delete(user)
    await session.commit()

    logger.info("Account deleted: user_id=%s username=%s", user_id, username)

    _clear_auth_cookies(request, response)

    return {"detail": "Account and all associated data have been permanently deleted"}


# --- API Keys ---


@router.get("/api-keys", summary="List API keys")
@limiter.limit(RateLimits.SESSION_READ)
async def list_api_keys(
    request: Request,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """List current user's active API keys."""
    from app.models.plan import ApiKey

    stmt = (
        select(ApiKey)
        .where(ApiKey.user_id == str(user.id), ApiKey.is_active.is_(True))
        .order_by(ApiKey.created_at.desc())
    )
    result = await session.execute(stmt)
    keys = result.scalars().all()
    return [
        {
            "id": str(k.id),
            "name": k.name,
            "prefix": k.key_prefix,
            "scopes": k.scopes,
            "created_at": k.created_at.isoformat() if k.created_at else None,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "expires_at": k.expires_at.isoformat() if k.expires_at else None,
        }
        for k in keys
    ]


@router.post("/api-keys", summary="Create API key", status_code=201)
@limiter.limit(RateLimits.SESSION_WRITE)
async def create_api_key(
    request: Request,
    body: dict = Body(...),
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Create a new API key for the current user."""
    import secrets

    from app.models.plan import ApiKey

    name = body.get("name", "Unnamed Key")
    scopes = body.get("scopes", [])

    raw_key = f"sk_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:10]

    api_key = ApiKey(
        user_id=str(user.id),
        name=name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        scopes=scopes,
        is_active=True,
    )
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)

    await audit_log_event(
        session,
        AuditEventType.API_KEY_CREATED,
        user_id=str(user.id),
        details={"key_name": name},
        request=request,
    )

    return {"id": str(api_key.id), "name": name, "key": raw_key, "prefix": key_prefix}


@router.delete("/api-keys/{key_id}", summary="Revoke API key")
@limiter.limit(RateLimits.SESSION_WRITE)
async def revoke_api_key(
    key_id: str,
    request: Request,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Revoke an API key belonging to the current user."""
    from app.models.plan import ApiKey

    stmt = select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == str(user.id))
    result = await session.execute(stmt)
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    api_key.is_active = False
    await session.commit()

    await audit_log_event(
        session,
        AuditEventType.API_KEY_REVOKED,
        user_id=str(user.id),
        details={"key_name": api_key.name},
        request=request,
    )

    return {"detail": "API key revoked"}


# --- Activity Log ---


@router.get("/activity", summary="Get recent activity")
@limiter.limit(RateLimits.SESSION_READ)
async def get_user_activity(
    request: Request,
    limit: int = 20,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Return recent audit log entries for the current user."""
    from app.models.audit_log import AuditLog

    stmt = (
        select(AuditLog)
        .where(AuditLog.user_id == str(user.id))
        .order_by(AuditLog.created_at.desc())
        .limit(min(limit, 100))
    )
    result = await session.execute(stmt)
    logs = result.scalars().all()
    return [
        {
            "id": str(entry.id),
            "event_type": entry.event_type,
            "details": entry.details,
            "ip_address": entry.ip_address,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
        }
        for entry in logs
    ]
