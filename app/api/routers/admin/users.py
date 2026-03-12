"""Admin user management endpoints."""

from __future__ import annotations

import logging
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    PaginatedResponse,
    UserAdminResponse,
    UserCreateRequest,
    UserUpdateRequest,
)
from app.core.config import settings
from app.core.database import get_async_session
from app.core.rbac import Permission, require_permission
from app.core.security import get_password_hash
from app.models.audit_log import AuditEventType
from app.models.user import User
from app.services.system.audit import log_event as audit_log_event

logger = logging.getLogger("spectra.admin")

router = APIRouter()

APP_DIR = Path(__file__).resolve().parent.parent.parent.parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
templates.env.globals["app_name"] = settings.APP_NAME


def _get_ui_user(request: Request) -> dict | None:
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        from app.core.security import decode_token, is_token_blacklisted

        if is_token_blacklisted(token):
            return None
        payload = decode_token(token)
        if payload and payload.get("sub"):
            return payload
    except Exception:
        logger.debug("Failed to decode UI token", exc_info=True)
        return None


@router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
async def admin_page(request: Request):
    """Serve the admin panel UI."""
    user = _get_ui_user(request)
    if not user:
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url="/login", status_code=303)
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return templates.TemplateResponse(
        "admin.html",
        {"request": request, "title": f"{settings.APP_NAME} | Admin"},
    )


@router.get("/api/admin/users")
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
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

    items = [
        UserAdminResponse(
            id=u.id,
            username=u.username,
            email=u.email,
            role=u.role,
            is_active=u.is_active,
            is_superuser=u.is_superuser,
            plan_id=u.plan_id,
            created_at=u.created_at.isoformat(),
            updated_at=u.updated_at.isoformat(),
        )
        for u in rows
    ]
    return PaginatedResponse(items=items, total=total, page=page, per_page=per_page)


@router.get("/api/admin/users/{user_id}")
async def get_user(
    user_id: str,
    _user: User = require_permission(Permission.MANAGE_USERS),
    session: AsyncSession = Depends(get_async_session),
) -> UserAdminResponse:
    row = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return UserAdminResponse(
        id=row.id,
        username=row.username,
        email=row.email,
        role=row.role,
        is_active=row.is_active,
        is_superuser=row.is_superuser,
        plan_id=row.plan_id,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.post("/api/admin/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreateRequest,
    request: Request,
    admin: User = require_permission(Permission.MANAGE_USERS),
    session: AsyncSession = Depends(get_async_session),
) -> UserAdminResponse:
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
        is_active=True,
        is_superuser=body.role == "admin",
        plan_id=body.plan_id,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)

    await audit_log_event(
        session,
        AuditEventType.SETTINGS_CHANGED,
        user_id=admin.id,
        details={"action": "user_created", "target_user": user.username},
        request=request,
    )
    await session.commit()

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


@router.put("/api/admin/users/{user_id}")
async def update_user(
    user_id: str,
    body: UserUpdateRequest,
    request: Request,
    admin: User = require_permission(Permission.MANAGE_USERS),
    session: AsyncSession = Depends(get_async_session),
) -> UserAdminResponse:
    row = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

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

    await audit_log_event(
        session,
        AuditEventType.SETTINGS_CHANGED,
        user_id=admin.id,
        details={"action": "user_updated", "target_user": row.username},
        request=request,
    )
    await session.commit()
    await session.refresh(row)

    return UserAdminResponse(
        id=row.id,
        username=row.username,
        email=row.email,
        role=row.role,
        is_active=row.is_active,
        is_superuser=row.is_superuser,
        plan_id=row.plan_id,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.delete("/api/admin/users/{user_id}", status_code=status.HTTP_200_OK)
async def deactivate_user(
    user_id: str,
    request: Request,
    admin: User = require_permission(Permission.MANAGE_USERS),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    row = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    if row.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")

    row.is_active = False
    await audit_log_event(
        session,
        AuditEventType.SETTINGS_CHANGED,
        user_id=admin.id,
        details={"action": "user_deactivated", "target_user": row.username},
        request=request,
    )
    await session.commit()
    return {"detail": "User deactivated"}


@router.post("/api/admin/users/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    request: Request,
    admin: User = require_permission(Permission.MANAGE_USERS),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    row = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    temp_password = secrets.token_urlsafe(16)
    row.hashed_password = get_password_hash(temp_password)
    await audit_log_event(
        session,
        AuditEventType.PASSWORD_CHANGED,
        user_id=admin.id,
        details={"action": "password_reset", "target_user": row.username},
        request=request,
    )
    await session.commit()
    return {"detail": "Password reset", "temporary_password": temp_password}
