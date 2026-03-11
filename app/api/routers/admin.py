"""Admin panel API router.

Provides user management, plan management, audit logs, and dashboard
statistics. All endpoints require the admin role.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_active_user
from app.api.schemas import (
    PaginatedResponse,
    PlanCreateRequest,
    PlanResponse,
    PlanUpdateRequest,
    UserAdminResponse,
    UserCreateRequest,
    UserUpdateRequest,
)
from app.core.config import settings
from app.core.database import get_async_session
from app.core.rbac import Permission, require_permission
from app.core.security import get_password_hash
from app.models.audit_log import AuditEventType, AuditLog
from app.models.mission import Mission
from app.models.plan import Plan
from app.models.user import User
from app.services.system.audit import log_event as audit_log_event

logger = logging.getLogger("spectra.admin")

router = APIRouter()

APP_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
templates.env.globals["app_name"] = settings.APP_NAME


# ---------------------------------------------------------------------------
# UI page
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# User Management
# ---------------------------------------------------------------------------


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
    row = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
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
        await session.execute(
            select(User.id).where(
                or_(User.username == body.username, User.email == body.email)
            )
        )
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
    row = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
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
            await session.execute(
                select(User.id).where(User.email == body.email, User.id != user_id)
            )
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
    row = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
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
    row = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
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


# ---------------------------------------------------------------------------
# Plan Management
# ---------------------------------------------------------------------------


@router.get("/api/admin/plans")
async def list_plans(
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
) -> list[PlanResponse]:
    rows = (
        await session.execute(select(Plan).order_by(Plan.sort_order, Plan.name))
    ).scalars().all()
    return [
        PlanResponse(
            id=p.id,
            name=p.name,
            display_name=p.display_name,
            description=p.description,
            is_active=p.is_active,
            is_default=p.is_default,
            sort_order=p.sort_order,
            max_concurrent_missions=p.max_concurrent_missions,
            max_missions_per_month=p.max_missions_per_month,
            max_targets=p.max_targets,
            max_api_requests_per_hour=p.max_api_requests_per_hour,
            max_api_requests_per_day=p.max_api_requests_per_day,
            sandbox_max_containers=p.sandbox_max_containers,
            max_storage_mb=p.max_storage_mb,
            sandbox_resource_tier=p.sandbox_resource_tier,
            features=p.features,
        )
        for p in rows
    ]


@router.post("/api/admin/plans", status_code=status.HTTP_201_CREATED)
async def create_plan(
    body: PlanCreateRequest,
    request: Request,
    admin: User = require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
) -> PlanResponse:
    dup = (
        await session.execute(select(Plan.id).where(Plan.name == body.name))
    ).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=409, detail="Plan name already exists")

    plan = Plan(
        name=body.name,
        display_name=body.display_name,
        description=body.description,
        is_active=True,
        is_default=body.is_default,
        sort_order=body.sort_order,
        max_concurrent_missions=body.max_concurrent_missions,
        max_missions_per_month=body.max_missions_per_month,
        max_targets=body.max_targets,
        max_api_requests_per_hour=body.max_api_requests_per_hour,
        max_api_requests_per_day=body.max_api_requests_per_day,
        sandbox_max_containers=body.sandbox_max_containers,
        max_storage_mb=body.max_storage_mb,
        sandbox_resource_tier=body.sandbox_resource_tier,
        features=body.features,
    )
    session.add(plan)
    await session.flush()
    await session.refresh(plan)

    await audit_log_event(
        session,
        AuditEventType.SETTINGS_CHANGED,
        user_id=admin.id,
        details={"action": "plan_created", "plan": plan.name},
        request=request,
    )
    await session.commit()

    return PlanResponse(
        id=plan.id,
        name=plan.name,
        display_name=plan.display_name,
        description=plan.description,
        is_active=plan.is_active,
        is_default=plan.is_default,
        sort_order=plan.sort_order,
        max_concurrent_missions=plan.max_concurrent_missions,
        max_missions_per_month=plan.max_missions_per_month,
        max_targets=plan.max_targets,
        max_api_requests_per_hour=plan.max_api_requests_per_hour,
        max_api_requests_per_day=plan.max_api_requests_per_day,
        sandbox_max_containers=plan.sandbox_max_containers,
        max_storage_mb=plan.max_storage_mb,
        sandbox_resource_tier=plan.sandbox_resource_tier,
        features=plan.features,
    )


@router.put("/api/admin/plans/{plan_id}")
async def update_plan(
    plan_id: str,
    body: PlanUpdateRequest,
    request: Request,
    admin: User = require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
) -> PlanResponse:
    plan = (
        await session.execute(select(Plan).where(Plan.id == plan_id))
    ).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    for field in (
        "display_name",
        "description",
        "is_default",
        "sort_order",
        "max_concurrent_missions",
        "max_missions_per_month",
        "max_targets",
        "max_api_requests_per_hour",
        "max_api_requests_per_day",
        "sandbox_max_containers",
        "max_storage_mb",
        "sandbox_resource_tier",
        "features",
    ):
        val = getattr(body, field, None)
        if val is not None:
            setattr(plan, field, val)

    await audit_log_event(
        session,
        AuditEventType.SETTINGS_CHANGED,
        user_id=admin.id,
        details={"action": "plan_updated", "plan": plan.name},
        request=request,
    )
    await session.commit()
    await session.refresh(plan)

    return PlanResponse(
        id=plan.id,
        name=plan.name,
        display_name=plan.display_name,
        description=plan.description,
        is_active=plan.is_active,
        is_default=plan.is_default,
        sort_order=plan.sort_order,
        max_concurrent_missions=plan.max_concurrent_missions,
        max_missions_per_month=plan.max_missions_per_month,
        max_targets=plan.max_targets,
        max_api_requests_per_hour=plan.max_api_requests_per_hour,
        max_api_requests_per_day=plan.max_api_requests_per_day,
        sandbox_max_containers=plan.sandbox_max_containers,
        max_storage_mb=plan.max_storage_mb,
        sandbox_resource_tier=plan.sandbox_resource_tier,
        features=plan.features,
    )


@router.delete("/api/admin/plans/{plan_id}")
async def deactivate_plan(
    plan_id: str,
    request: Request,
    admin: User = require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    plan = (
        await session.execute(select(Plan).where(Plan.id == plan_id))
    ).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    plan.is_active = False
    await audit_log_event(
        session,
        AuditEventType.SETTINGS_CHANGED,
        user_id=admin.id,
        details={"action": "plan_deactivated", "plan": plan.name},
        request=request,
    )
    await session.commit()
    return {"detail": "Plan deactivated"}


# ---------------------------------------------------------------------------
# Audit Logs
# ---------------------------------------------------------------------------


@router.get("/api/admin/audit-logs")
async def list_audit_logs(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user_id: str | None = Query(None),
    event_type: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    _user: User = require_permission(Permission.VIEW_AUDIT_LOG),
    session: AsyncSession = Depends(get_async_session),
) -> PaginatedResponse:
    stmt = select(AuditLog)
    count_stmt = select(func.count()).select_from(AuditLog)

    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
        count_stmt = count_stmt.where(AuditLog.user_id == user_id)
    if event_type:
        stmt = stmt.where(AuditLog.event_type == event_type)
        count_stmt = count_stmt.where(AuditLog.event_type == event_type)
    if date_from:
        dt = datetime.fromisoformat(date_from).replace(tzinfo=UTC)
        stmt = stmt.where(AuditLog.created_at >= dt)
        count_stmt = count_stmt.where(AuditLog.created_at >= dt)
    if date_to:
        dt = datetime.fromisoformat(date_to).replace(tzinfo=UTC)
        stmt = stmt.where(AuditLog.created_at <= dt)
        count_stmt = count_stmt.where(AuditLog.created_at <= dt)

    total = (await session.execute(count_stmt)).scalar() or 0
    offset = (page - 1) * per_page
    stmt = stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(per_page)
    rows = (await session.execute(stmt)).scalars().all()

    items = [
        {
            "id": r.id,
            "user_id": r.user_id,
            "event_type": r.event_type,
            "details": r.details,
            "ip_address": r.ip_address,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
    return PaginatedResponse(items=items, total=total, page=page, per_page=per_page)


# ---------------------------------------------------------------------------
# Dashboard Stats
# ---------------------------------------------------------------------------


@router.get("/api/admin/stats")
async def admin_stats(
    _user: User = require_permission(Permission.MANAGE_USERS),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    total_users = (
        await session.execute(select(func.count()).select_from(User))
    ).scalar() or 0
    active_users = (
        await session.execute(
            select(func.count()).select_from(User).where(User.is_active.is_(True))
        )
    ).scalar() or 0

    total_plans = (
        await session.execute(select(func.count()).select_from(Plan))
    ).scalar() or 0

    total_missions = 0
    try:
        total_missions = (
            await session.execute(select(func.count()).select_from(Mission))
        ).scalar() or 0
    except Exception:
        pass

    total_audit_events = (
        await session.execute(select(func.count()).select_from(AuditLog))
    ).scalar() or 0

    role_result = await session.execute(
        select(User.role, func.count()).group_by(User.role)
    )
    role_counts = {r: 0 for r in ("admin", "operator", "viewer")}
    for role_name, cnt in role_result.all():
        if role_name in role_counts:
            role_counts[role_name] = cnt

    # Service topology
    from app.services.gateway.service_registry import get_service_registry
    svc_registry = get_service_registry()
    topology = svc_registry.get_service_topology()

    return {
        "total_users": total_users,
        "active_users": active_users,
        "total_plans": total_plans,
        "total_missions": total_missions,
        "total_audit_events": total_audit_events,
        "role_counts": role_counts,
        "service_topology": topology,
    }


# ---------------------------------------------------------------------------
# Server Provisioning
# ---------------------------------------------------------------------------


@router.post("/api/admin/servers/verify")
async def verify_server_connection(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    _perm=require_permission(Permission.MANAGE_SETTINGS),
):
    """Test SSH connectivity to a remote server without making changes."""
    data = await request.json()
    from app.services.provisioning import ServerProvisioner
    from app.services.provisioning.provisioner import ServerConfig

    config = ServerConfig(
        host=data["host"],
        port=data.get("port", 22),
        username=data.get("username", "root"),
        password=data.get("password"),
        private_key=data.get("private_key"),
    )

    provisioner = ServerProvisioner()
    result = await provisioner.verify_connection(config)
    return result


@router.post("/api/admin/servers/provision", status_code=status.HTTP_202_ACCEPTED)
async def provision_server(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    _perm=require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
):
    """Auto-install and configure a Spectra service on a remote server.

    Connects via SSH, installs Docker if needed, pulls images, starts the service,
    and verifies health.
    """
    data = await request.json()
    from app.services.provisioning import ServerProvisioner
    from app.services.provisioning.provisioner import ServerConfig

    service_type = data["service_type"]
    if service_type != "sandbox_worker":
        raise HTTPException(400, f"Invalid service_type: {service_type}")

    config = ServerConfig(
        host=data["host"],
        port=data.get("port", 22),
        username=data.get("username", "root"),
        password=data.get("password"),
        private_key=data.get("private_key"),
        service_type=service_type,
        service_port=data.get("service_port", 8080),
        extra_env=data.get("extra_env", {}),
    )

    provisioner = ServerProvisioner()
    result = await provisioner.provision(config)

    await audit_log_event(
        session,
        AuditEventType.SETTINGS_CHANGED,
        user_id=current_user.id,
        details={
            "action": "server_provisioned" if result.success else "server_provision_failed",
            "host": config.host,
            "service_type": service_type,
            "success": result.success,
            "error": result.error or None,
        },
        request=request,
    )

    return {
        "success": result.success,
        "service_url": result.service_url,
        "health_check_passed": result.health_check_passed,
        "logs": result.logs,
        "error": result.error,
    }


@router.post("/api/admin/servers/deprovision")
async def deprovision_server(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    _perm=require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
):
    """Remove a Spectra service from a remote server."""
    data = await request.json()
    from app.services.provisioning import ServerProvisioner
    from app.services.provisioning.provisioner import ServerConfig

    config = ServerConfig(
        host=data["host"],
        port=data.get("port", 22),
        username=data.get("username", "root"),
        password=data.get("password"),
        private_key=data.get("private_key"),
        service_type="sandbox_worker",
    )

    provisioner = ServerProvisioner()
    result = await provisioner.deprovision(config)

    await audit_log_event(
        session,
        AuditEventType.SETTINGS_CHANGED,
        user_id=current_user.id,
        details={
            "action": "server_deprovisioned" if result.success else "server_deprovision_failed",
            "host": config.host,
            "service_type": config.service_type,
        },
        request=request,
    )

    return {
        "success": result.success,
        "logs": result.logs,
        "error": result.error,
    }


# ---------------------------------------------------------------------------
# Server Pool Management
# ---------------------------------------------------------------------------


@router.get("/api/admin/servers")
async def list_server_nodes(
    service_type: str | None = None,
    session: AsyncSession = Depends(get_async_session),
    _admin: User = require_permission("admin"),  # type: ignore[assignment]
):
    """List all registered server nodes."""
    from app.services.scaling import get_pool_manager
    pool = get_pool_manager()
    return await pool.list_nodes(session, service_type=service_type)


@router.post("/api/admin/servers", status_code=201)
async def add_server_node(
    name: str = Body(...),
    service_type: str = Body(..., pattern=r"^(sandbox_worker|db_replica|storage)$"),
    url: str = Body(...),
    api_key: str | None = Body(None),
    is_primary: bool = Body(False),
    weight: int = Body(1, ge=1, le=100),
    max_capacity: int = Body(10, ge=1, le=1000),
    session: AsyncSession = Depends(get_async_session),
    _admin: User = require_permission("admin"),  # type: ignore[assignment]
):
    """Register a new server node in the pool."""
    from app.services.scaling import get_pool_manager
    pool = get_pool_manager()
    node = await pool.add_node(
        session, service_type, name, url,
        api_key=api_key, is_primary=is_primary,
        weight=weight, max_capacity=max_capacity,
    )
    await session.commit()
    logger.info("Server node added: %s (%s)", name, service_type)
    return node


@router.delete("/api/admin/servers/{node_id}")
async def remove_server_node(
    node_id: int,
    session: AsyncSession = Depends(get_async_session),
    _admin: User = require_permission("admin"),  # type: ignore[assignment]
):
    """Remove a server node from the pool."""
    from app.services.scaling import get_pool_manager
    pool = get_pool_manager()
    removed = await pool.remove_node(session, node_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Node not found")
    await session.commit()
    return {"status": "removed"}


@router.patch("/api/admin/servers/{node_id}")
async def update_server_node(
    node_id: int,
    updates: dict = Body(...),
    session: AsyncSession = Depends(get_async_session),
    _admin: User = require_permission("admin"),  # type: ignore[assignment]
):
    """Update a server node's configuration."""
    from app.services.scaling import get_pool_manager
    allowed_fields = {"name", "url", "api_key", "is_active", "is_primary", "weight", "max_capacity"}
    filtered = {k: v for k, v in updates.items() if k in allowed_fields}
    pool = get_pool_manager()
    node = await pool.update_node(session, node_id, **filtered)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    await session.commit()
    return node


@router.post("/api/admin/servers/health-check")
async def check_all_server_health(
    _admin: User = require_permission("admin"),  # type: ignore[assignment]
):
    """Run health checks on all active server nodes."""
    from app.services.scaling import get_pool_manager
    pool = get_pool_manager()
    results = await pool.health_check_all()
    return results
