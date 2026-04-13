"""Admin user management endpoints."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TypedDict

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    _decode_access_payload,
    _extract_request_token,
    _load_active_user_from_payload_with_session,
    validate_uuid_param,
)
from app.api.schemas import (
    AdminUserCreate,
    AdminUserCreateResponse,
    AdminUserUpdate,
    PaginatedResponse,
    UserAdminResponse,
)
from app.core.config import settings
from app.core.constants import API_DEFAULT_PAGE_SIZE, API_MAX_PAGE_SIZE
from app.core.database import get_async_session
from app.core.rbac import Permission, require_permission
from app.core.security import create_password_reset_token, get_password_hash
from app.core.templates import templates
from app.models.audit_log import AuditEventType
from app.models.exploit import Exploit
from app.models.finding import Finding
from app.models.mission import Mission
from app.models.pentest_session import PentestSession
from app.models.plan import ApiKey, Plan, Subscription, UsageRecord
from app.models.target import Target
from app.models.user import User
from app.models.user_preferences import UserPreferences
from app.services.billing import PaymentService
from app.services.billing.entitlements import (
    ENTITLEMENT_ACTIVE_SUBSCRIPTION_STATUSES,
    sync_user_plan_mirror,
)
from app.services.system.audit import log_event as audit_log_event
from app.services.system.rollback import create_snapshot

logger = logging.getLogger(__name__)

router = APIRouter()

class SubscriptionBeforeState(TypedDict):
    plan_id: str
    status: str
    trial_ends_at: str | None
    current_period_start: str | None
    current_period_end: str | None
    external_subscription_id: str | None
    external_customer_id: str | None
    payment_provider: str | None
    metadata: dict | None


class UserBeforeState(TypedDict):
    is_active: bool
    role: str
    is_superuser: bool
    plan_id: str | None
    email: str
    subscription: SubscriptionBeforeState | None


UserAuditDetail = str | bool | None | list[str]
UserAuditEvent = tuple[AuditEventType, dict[str, UserAuditDetail]]


def _to_user_admin_response(user: User, *, effective_plan_id: str | None = None) -> UserAdminResponse:
    return UserAdminResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        plan_id=effective_plan_id,
        created_at=user.created_at.isoformat(),
        updated_at=user.updated_at.isoformat(),
    )


def _to_admin_user_create_response(
    user: User, activation_url: str | None, *, effective_plan_id: str | None = None
) -> AdminUserCreateResponse:
    return AdminUserCreateResponse(
        **_to_user_admin_response(user, effective_plan_id=effective_plan_id).model_dump(),
        activation_url=activation_url,
    )


async def _get_user_or_404(session: AsyncSession, user_id: str) -> User:
    validate_uuid_param(user_id, "user_id")
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


async def _active_superuser_count(session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(User)
        .where(
            User.is_superuser.is_(True),
            User.is_active.is_(True),
        )
    )
    return result.scalar_one() or 0


async def _ensure_not_last_active_superuser(session: AsyncSession, user: User) -> None:
    if user.is_superuser and user.is_active and await _active_superuser_count(session) <= 1:
        raise HTTPException(status_code=409, detail="Cannot delete the last administrator account")


def _plan_id_value(plan_id: object | None) -> str | None:
    return str(plan_id) if plan_id else None


def _serialize_subscription_before_state(subscription: Subscription | None) -> SubscriptionBeforeState | None:
    if subscription is None:
        return None

    return {
        "plan_id": str(subscription.plan_id),
        "status": subscription.status,
        "trial_ends_at": subscription.trial_ends_at.isoformat() if subscription.trial_ends_at else None,
        "current_period_start": subscription.current_period_start.isoformat() if subscription.current_period_start else None,
        "current_period_end": subscription.current_period_end.isoformat() if subscription.current_period_end else None,
        "external_subscription_id": subscription.external_subscription_id,
        "external_customer_id": subscription.external_customer_id,
        "payment_provider": subscription.payment_provider,
        "metadata": subscription.metadata_,
    }


def _subscription_state_requires_remote_recreation(subscription_state: SubscriptionBeforeState | None) -> bool:
    if not subscription_state:
        return False

    payment_provider = (subscription_state.get("payment_provider") or "").strip().lower()
    return payment_provider == "stripe" or bool(
        subscription_state.get("external_subscription_id") or subscription_state.get("external_customer_id")
    )


def _user_update_is_snapshot_restorable(before_state: UserBeforeState, *, plan_change_requested: bool) -> bool:
    if not plan_change_requested:
        return True
    return not _subscription_state_requires_remote_recreation(before_state.get("subscription"))


async def _get_effective_plan_ids(session: AsyncSession, user_ids: list[str]) -> dict[str, str]:
    if not user_ids:
        return {}

    result = await session.execute(
        select(Subscription.user_id, Subscription.plan_id)
        .join(Plan, Plan.id == Subscription.plan_id)
        .where(
            Subscription.user_id.in_(user_ids),
            Subscription.status.in_(tuple(ENTITLEMENT_ACTIVE_SUBSCRIPTION_STATUSES)),
            Plan.is_active.is_(True),
        )
    )
    return {str(user_id): str(plan_id) for user_id, plan_id in result.all()}


async def _get_effective_plan_id(session: AsyncSession, user_id: str) -> str | None:
    return (await _get_effective_plan_ids(session, [user_id])).get(user_id)


async def _build_user_before_state(session: AsyncSession, user: User) -> UserBeforeState:
    subscription = (
        await session.execute(select(Subscription).where(Subscription.user_id == str(user.id)))
    ).scalar_one_or_none()
    return {
        "is_active": user.is_active,
        "role": user.role,
        "is_superuser": user.is_superuser,
        "plan_id": await _get_effective_plan_id(session, str(user.id)),
        "email": user.email,
        "subscription": _serialize_subscription_before_state(subscription),
    }


async def _validate_plan_or_404(session: AsyncSession, plan_id: str) -> Plan:
    plan = (await session.execute(select(Plan).where(Plan.id == plan_id))).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


async def _cancel_remote_authoritative_subscription(subscription: Subscription) -> None:
    if not PaymentService.is_stripe_authoritative_subscription(subscription):
        return
    if not subscription.external_subscription_id:
        raise HTTPException(
            status_code=409,
            detail="Cannot safely override a Stripe-backed subscription without its external subscription ID",
        )

    billing_service = PaymentService()
    try:
        cancelled = await billing_service.cancel_external_subscription(subscription)
    except (ImportError, OSError, RuntimeError, ValueError):
        logger.exception(
            "Failed to cancel remote Stripe subscription before applying admin override for user %s",
            subscription.user_id,
        )
        raise HTTPException(
            status_code=502,
            detail="Failed to cancel remote Stripe subscription before applying admin override",
        ) from None

    if not cancelled:
        raise HTTPException(
            status_code=502,
            detail="Failed to cancel remote Stripe subscription before applying admin override",
        )


async def _sync_user_subscription_assignment(session: AsyncSession, user: User, plan_id: str | None) -> None:
    requested_plan_id = _plan_id_value(plan_id)
    if requested_plan_id is not None:
        await _validate_plan_or_404(session, requested_plan_id)

    sub = (await session.execute(select(Subscription).where(Subscription.user_id == str(user.id)))).scalar_one_or_none()
    now = datetime.now(UTC)

    if sub is not None and PaymentService.is_stripe_authoritative_subscription(sub):
        await _cancel_remote_authoritative_subscription(sub)

    if requested_plan_id:
        if sub is None:
            sub = Subscription(
                user_id=str(user.id),
                plan_id=requested_plan_id,
                status="active",
                payment_provider="manual",
                current_period_start=now,
            )
            session.add(sub)
        else:
            sub.plan_id = requested_plan_id
            sub.status = "active"
            sub.current_period_start = now
            sub.current_period_end = None
            sub.trial_ends_at = None
    elif sub is not None:
        sub.status = "cancelled"
        sub.current_period_end = now
    else:
        user.plan_id = None
        return

    sub.payment_provider = "manual"
    sub.external_subscription_id = None
    sub.external_customer_id = None
    sub.metadata_ = None

    await sync_user_plan_mirror(session, user=user)


def _has_reversible_user_update(body: AdminUserUpdate, user: User, *, plan_change_requested: bool) -> bool:
    return any(
        [
            body.is_active is not None and body.is_active != user.is_active,
            body.role is not None and body.role != user.role,
            plan_change_requested,
        ]
    )


def _record_user_change(
    *,
    changed_fields: list[str],
    audit_events: list[UserAuditEvent],
    field_name: str,
    before: str | bool | None,
    after: str | bool | None,
    event_type: AuditEventType | None = None,
    details: dict[str, UserAuditDetail] | None = None,
) -> None:
    if before == after:
        return

    changed_fields.append(field_name)
    if event_type and details is not None:
        audit_events.append((event_type, details))


async def _build_user_update_audit_events(
    session: AsyncSession, before_state: UserBeforeState, user: User
) -> list[UserAuditEvent]:
    changed_fields: list[str] = []
    audit_events: list[UserAuditEvent] = []
    current_plan_id = await _get_effective_plan_id(session, str(user.id))

    _record_user_change(
        changed_fields=changed_fields,
        audit_events=audit_events,
        field_name="role",
        before=before_state["role"],
        after=user.role,
        event_type=AuditEventType.USER_ROLE_CHANGED,
        details={
            "target_user": user.username,
            "old_role": before_state["role"],
            "new_role": user.role,
        },
    )
    _record_user_change(
        changed_fields=changed_fields,
        audit_events=audit_events,
        field_name="is_active",
        before=before_state["is_active"],
        after=user.is_active,
        event_type=AuditEventType.USER_STATUS_CHANGED,
        details={
            "target_user": user.username,
            "old_is_active": before_state["is_active"],
            "new_is_active": user.is_active,
        },
    )
    _record_user_change(
        changed_fields=changed_fields,
        audit_events=audit_events,
        field_name="plan_id",
        before=before_state["plan_id"],
        after=current_plan_id,
        event_type=AuditEventType.PLAN_CHANGED,
        details={
            "target_user": user.username,
            "old_plan_id": before_state["plan_id"],
            "new_plan_id": current_plan_id,
        },
    )
    _record_user_change(
        changed_fields=changed_fields,
        audit_events=audit_events,
        field_name="email",
        before=before_state["email"],
        after=user.email,
    )

    if not audit_events or "email" in changed_fields:
        audit_events.append(
            (
                AuditEventType.SETTINGS_CHANGED,
                {
                    "action": "user_updated",
                    "target_user": user.username,
                    "changed_fields": changed_fields,
                },
            )
        )

    return audit_events


@router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
async def admin_page(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
):
    """Serve the admin panel UI."""
    from fastapi.responses import RedirectResponse

    token, _source = _extract_request_token(request)
    if not token:
        return RedirectResponse(url="/login", status_code=303)

    payload = await _decode_access_payload(token)
    if payload is None:
        return RedirectResponse(url="/login", status_code=303)

    user = await _load_active_user_from_payload_with_session(payload, session)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    if user.role != "admin" and not user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    maintenance_active = False
    try:
        from app.services.system.runtime_settings import get_runtime_setting_value

        maintenance_active = bool(await get_runtime_setting_value("MAINTENANCE_MODE"))
    except OSError:
        logger.debug("Failed to load maintenance mode setting", exc_info=True)

    return templates.TemplateResponse(
        "admin.html",
        {"request": request, "title": f"{settings.APP_NAME} | Admin", "maintenance_active": maintenance_active},
    )


@router.get("/api/admin/users")
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(API_DEFAULT_PAGE_SIZE, ge=1, le=API_MAX_PAGE_SIZE),
    search: str | None = Query(None, max_length=100),
    role: str | None = Query(None, pattern="^(admin|operator|viewer)$"),
    is_active: bool | None = Query(None),
    _user: User = require_permission(Permission.MANAGE_USERS),
    session: AsyncSession = Depends(get_async_session),
) -> PaginatedResponse:
    stmt = select(User)
    count_stmt = select(func.count()).select_from(User)

    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like_pat = f"%{escaped}%"
        filt = or_(User.username.ilike(like_pat), User.email.ilike(like_pat))
        stmt = stmt.where(filt)
        count_stmt = count_stmt.where(filt)

    if role:
        stmt = stmt.where(User.role == role)
        count_stmt = count_stmt.where(User.role == role)

    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
        count_stmt = count_stmt.where(User.is_active == is_active)

    total = (await session.execute(count_stmt)).scalar() or 0
    offset = (page - 1) * per_page
    stmt = stmt.order_by(User.created_at.desc()).offset(offset).limit(per_page)
    rows = (await session.execute(stmt)).scalars().all()

    effective_plan_ids = await _get_effective_plan_ids(session, [str(user.id) for user in rows])
    items = [
        _to_user_admin_response(user, effective_plan_id=effective_plan_ids.get(str(user.id))) for user in rows
    ]
    return PaginatedResponse(items=items, total=total, page=page, per_page=per_page)


@router.get("/api/admin/users/{user_id}")
async def get_user(
    user_id: str,
    _user: User = require_permission(Permission.MANAGE_USERS),
    session: AsyncSession = Depends(get_async_session),
) -> UserAdminResponse:
    user = await _get_user_or_404(session, user_id)
    return _to_user_admin_response(user, effective_plan_id=await _get_effective_plan_id(session, user_id))


@router.post("/api/admin/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: AdminUserCreate,
    request: Request = None,  # type: ignore[assignment]
    admin: User = require_permission(Permission.MANAGE_USERS),
    session: AsyncSession = Depends(get_async_session),
) -> AdminUserCreateResponse:
    # Check uniqueness
    exists = (
        await session.execute(select(User.id).where(or_(User.username == body.username, User.email == body.email)))
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="Username or email already taken")

    user = User(
        username=body.username,
        email=body.email,
        hashed_password=get_password_hash(body.password),
        role=body.role,
        is_active=False,
        is_superuser=body.role == "admin",
        email_verified=False,
        plan_id=None,
    )
    session.add(user)
    await session.flush()
    await _sync_user_subscription_assignment(session, user, body.plan_id)
    await session.refresh(user)

    await audit_log_event(
        session,
        AuditEventType.USER_CREATED,
        user_id=admin.id,
        details={"action": "user_created", "target_user": user.username, "target_user_id": str(user.id)},
        request=request,
    )
    await session.commit()

    activation_url = None
    try:
        from app.services.auth.email_verification import (
            build_email_verification_url,
            send_registration_verification_email,
        )

        email_sent = False
        if settings.smtp_configured:
            email_sent = await send_registration_verification_email(request, user.username, user.email, str(user.id))
        if not email_sent:
            activation_url = build_email_verification_url(request, str(user.id))
    except Exception:
        logger.exception("Failed to prepare admin-created user activation flow for %s", user.username)
        from app.services.auth.email_verification import build_email_verification_url

        activation_url = build_email_verification_url(request, str(user.id))

    effective_plan_id = await _get_effective_plan_id(session, str(user.id))
    return _to_admin_user_create_response(user, activation_url, effective_plan_id=effective_plan_id)


@router.put("/api/admin/users/{user_id}")
async def update_user(
    user_id: str,
    body: AdminUserUpdate,
    request: Request = None,  # type: ignore[assignment]
    admin: User = require_permission(Permission.MANAGE_USERS),
    session: AsyncSession = Depends(get_async_session),
) -> UserAdminResponse:
    row = await _get_user_or_404(session, user_id)
    requested_plan_id = body.plan_id or None if "plan_id" in body.model_fields_set else None

    effective_is_superuser = body.role == "admin" if body.role is not None else row.is_superuser
    effective_is_active = body.is_active if body.is_active is not None else row.is_active
    if (
        row.is_superuser
        and row.is_active
        and not (effective_is_superuser and effective_is_active)
        and await _active_superuser_count(session) <= 1
    ):
        raise HTTPException(
            status_code=409,
            detail="Cannot remove or deactivate the last active superuser",
        )
    if body.is_active and not row.email_verified:
        raise HTTPException(status_code=400, detail="User must complete account activation before being activated")

    before_state = await _build_user_before_state(session, row)
    plan_change_requested = (
        "plan_id" in body.model_fields_set and _plan_id_value(requested_plan_id) != before_state["plan_id"]
    )

    if body.email is not None:
        dup = (
            await session.execute(select(User.id).where(User.email == body.email, User.id != user_id))
        ).scalar_one_or_none()
        if dup:
            raise HTTPException(status_code=409, detail="Email already in use")

    if _has_reversible_user_update(body, row, plan_change_requested=plan_change_requested) and _user_update_is_snapshot_restorable(
        before_state,
        plan_change_requested=plan_change_requested,
    ):
        await create_snapshot(
            session,
            actor_user_id=str(admin.id),
            entity_type="user",
            entity_id=str(row.id),
            action=f"User updated: {row.username}",
            before_state=dict(before_state),
        )
    elif plan_change_requested and _subscription_state_requires_remote_recreation(before_state.get("subscription")):
        logger.info(
            "Skipping rollback snapshot for user %s because the admin override cancels a Stripe-backed subscription remotely",
            row.id,
        )

    if body.role is not None:
        row.role = body.role
        row.is_superuser = body.role == "admin"
    if body.is_active is not None:
        row.is_active = body.is_active
    if plan_change_requested:
        await _sync_user_subscription_assignment(session, row, requested_plan_id)
    if body.email is not None:
        row.email = body.email

    if before_state["role"] != row.role or before_state["is_active"] != row.is_active:
        row.invalidated_before = datetime.now(UTC)

    await session.commit()
    await session.refresh(row)

    for event_type, details in await _build_user_update_audit_events(session, before_state, row):
        await audit_log_event(
            session,
            event_type,
            user_id=admin.id,
            details=details,
            request=request,
        )

    return _to_user_admin_response(row, effective_plan_id=await _get_effective_plan_id(session, user_id))


@router.delete("/api/admin/users/{user_id}", status_code=status.HTTP_200_OK)
async def deactivate_user(
    user_id: str,
    request: Request = None,  # type: ignore[assignment]
    admin: User = require_permission(Permission.MANAGE_USERS),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    row = await _get_user_or_404(session, user_id)
    if row.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")

    await _ensure_not_last_active_superuser(session, row)

    row.is_active = False
    await audit_log_event(
        session,
        AuditEventType.USER_STATUS_CHANGED,
        user_id=admin.id,
        details={"action": "user_deactivated", "target_user": row.username, "new_is_active": False},
        request=request,
    )
    await session.commit()
    return {"detail": "User deactivated"}


@router.post("/api/admin/users/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    request: Request = None,  # type: ignore[assignment]
    admin: User = require_permission(Permission.MANAGE_USERS),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    from app.services.email import EmailService

    row = await _get_user_or_404(session, user_id)

    reset_token = create_password_reset_token(str(row.id))
    base_url = settings.PLATFORM_BASE_URL or (str(request.base_url).rstrip("/") if request else "")
    reset_url = f"{base_url}/reset-password?token={reset_token}"

    try:
        sent = await EmailService().send_template(
            to=row.email,
            template_name="password_reset",
            subject=f"{settings.APP_NAME} - Password Reset",
            username=row.username,
            reset_url=reset_url,
        )
    except (OSError, RuntimeError, ConnectionError):
        logger.exception("Failed to send admin-triggered password reset email to user %s", row.id)
        raise HTTPException(status_code=503, detail="Failed to send password reset email")

    if not sent:
        raise HTTPException(status_code=503, detail="Failed to send password reset email")

    await audit_log_event(
        session,
        AuditEventType.PASSWORD_RESET,
        user_id=admin.id,
        details={"action": "password_reset", "target_user": row.username},
        request=request,
    )
    await session.commit()
    return {"detail": "Password reset email sent"}


@router.delete("/api/admin/users/{user_id}/purge")
async def purge_user(
    user_id: str,
    request: Request = None,  # type: ignore[assignment]
    admin: User = require_permission(Permission.MANAGE_USERS),
    session: AsyncSession = Depends(get_async_session),
):
    """Hard delete a user and all their data. Admin only."""
    target_user = await _get_user_or_404(session, user_id)

    if target_user.is_superuser and str(target_user.id) == str(admin.id):
        raise HTTPException(400, "Cannot purge your own superuser account")

    await _ensure_not_last_active_superuser(session, target_user)

    # Nullify audit log references
    await session.execute(
        text("UPDATE audit_logs SET user_id = NULL WHERE user_id = :uid"),
        {"uid": user_id},
    )

    await audit_log_event(
        session,
        AuditEventType.USER_DELETED,
        user_id=str(admin.id),
        details={"action": "user_purged", "target_user": target_user.username, "target_user_id": str(target_user.id)},
        request=request,
    )

    # Delete user-owned data explicitly (child → parent order)
    await session.execute(delete(Exploit).where(Exploit.user_id == user_id))
    await session.execute(delete(Finding).where(Finding.user_id == user_id))
    await session.execute(delete(Target).where(Target.user_id == user_id))
    await session.execute(delete(Mission).where(Mission.user_id == user_id))
    await session.execute(delete(PentestSession).where(PentestSession.user_id == user_id))
    await session.execute(delete(Subscription).where(Subscription.user_id == user_id))
    await session.execute(delete(ApiKey).where(ApiKey.user_id == user_id))
    await session.execute(delete(UsageRecord).where(UsageRecord.user_id == user_id))
    await session.execute(delete(UserPreferences).where(UserPreferences.user_id == user_id))

    await session.delete(target_user)
    await session.commit()
    return {"status": "purged", "user_id": user_id}
