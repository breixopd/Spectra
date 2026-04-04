"""Admin user management endpoints."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    _decode_access_payload,
    _extract_request_token,
    _load_active_user_from_payload_with_session,
    get_ui_user,
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
from app.models.audit_log import AuditEventType
from app.models.user import User
from app.services.system.audit import log_event as audit_log_event
from app.services.system.rollback import create_snapshot
from app.version import __version__

logger = logging.getLogger(__name__)

router = APIRouter()

APP_DIR = Path(__file__).resolve().parent.parent.parent.parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
templates.env.globals["app_name"] = settings.APP_NAME
templates.env.globals["version"] = __version__
templates.env.globals["get_nav_user"] = get_ui_user

UserBeforeState = dict[str, str | bool | None]
UserAuditDetail = str | bool | None | list[str]
UserAuditEvent = tuple[AuditEventType, dict[str, UserAuditDetail]]


def _to_user_admin_response(user: User) -> UserAdminResponse:
    return UserAdminResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        plan_id=user.plan_id,
        created_at=user.created_at.isoformat(),
        updated_at=user.updated_at.isoformat(),
    )


def _to_admin_user_create_response(user: User, activation_url: str | None) -> AdminUserCreateResponse:
    return AdminUserCreateResponse(**_to_user_admin_response(user).model_dump(), activation_url=activation_url)


async def _get_user_or_404(session: AsyncSession, user_id: str) -> User:
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


def _build_user_before_state(user: User) -> UserBeforeState:
    return {
        "is_active": user.is_active,
        "role": user.role,
        "is_superuser": user.is_superuser,
        "plan_id": _plan_id_value(user.plan_id),
        "email": user.email,
    }


def _has_reversible_user_update(body: AdminUserUpdate, user: User) -> bool:
    return any(
        [
            body.is_active is not None and body.is_active != user.is_active,
            body.role is not None and body.role != user.role,
            body.plan_id is not None,
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


def _build_user_update_audit_events(before_state: UserBeforeState, user: User) -> list[UserAuditEvent]:
    changed_fields: list[str] = []
    audit_events: list[UserAuditEvent] = []
    current_plan_id = _plan_id_value(user.plan_id)

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

    payload = _decode_access_payload(token)
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
        pass

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
        like_pat = f"%{search}%"
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

    items = [_to_user_admin_response(user) for user in rows]
    return PaginatedResponse(items=items, total=total, page=page, per_page=per_page)


@router.get("/api/admin/users/{user_id}")
async def get_user(
    user_id: str,
    _user: User = require_permission(Permission.MANAGE_USERS),
    session: AsyncSession = Depends(get_async_session),
) -> UserAdminResponse:
    return _to_user_admin_response(await _get_user_or_404(session, user_id))


@router.post("/api/admin/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: AdminUserCreate,
    request: Request = None,
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
        plan_id=body.plan_id,
    )
    session.add(user)
    await session.flush()
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
        from app.api.routers.public import _build_email_verification_url, _send_registration_verification_email

        email_sent = False
        if settings.smtp_configured:
            email_sent = await _send_registration_verification_email(request, user.username, user.email, str(user.id))
        if not email_sent:
            activation_url = _build_email_verification_url(request, str(user.id))
    except Exception:
        logger.exception("Failed to prepare admin-created user activation flow for %s", user.username)
        from app.api.routers.public import _build_email_verification_url

        activation_url = _build_email_verification_url(request, str(user.id))

    return _to_admin_user_create_response(user, activation_url)


@router.put("/api/admin/users/{user_id}")
async def update_user(
    user_id: str,
    body: AdminUserUpdate,
    request: Request = None,
    admin: User = require_permission(Permission.MANAGE_USERS),
    session: AsyncSession = Depends(get_async_session),
) -> UserAdminResponse:
    row = await _get_user_or_404(session, user_id)

    effective_is_superuser = body.role == "admin" if body.role is not None else row.is_superuser
    effective_is_active = body.is_active if body.is_active is not None else row.is_active
    if row.is_superuser and row.is_active and not (effective_is_superuser and effective_is_active):
        if await _active_superuser_count(session) <= 1:
            raise HTTPException(
                status_code=409,
                detail="Cannot remove or deactivate the last active superuser",
            )
    if body.is_active and not row.email_verified:
        raise HTTPException(status_code=400, detail="User must complete account activation before being activated")

    before_state = _build_user_before_state(row)
    if _has_reversible_user_update(body, row):
        await create_snapshot(
            session,
            actor_user_id=str(admin.id),
            entity_type="user",
            entity_id=str(row.id),
            action=f"User updated: {row.username}",
            before_state=before_state,
        )

    if body.role is not None:
        row.role = body.role
        row.is_superuser = body.role == "admin"
    if body.is_active is not None:
        row.is_active = body.is_active
    if body.plan_id is not None:
        row.plan_id = body.plan_id or None
    if body.email is not None:
        dup = (
            await session.execute(select(User.id).where(User.email == body.email, User.id != user_id))
        ).scalar_one_or_none()
        if dup:
            raise HTTPException(status_code=409, detail="Email already in use")
        row.email = body.email

    await session.commit()
    await session.refresh(row)

    for event_type, details in _build_user_update_audit_events(before_state, row):
        await audit_log_event(
            session,
            event_type,
            user_id=admin.id,
            details=details,
            request=request,
        )

    return _to_user_admin_response(row)


@router.delete("/api/admin/users/{user_id}", status_code=status.HTTP_200_OK)
async def deactivate_user(
    user_id: str,
    request: Request = None,
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
    request: Request = None,
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
    request: Request = None,
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

    await session.delete(target_user)
    await session.commit()
    return {"status": "purged", "user_id": user_id}
