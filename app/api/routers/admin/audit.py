"""Admin audit log and dashboard statistics endpoints."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import PaginatedResponse
from app.core.database import get_async_session
from app.core.rbac import Permission, require_permission
from app.models.audit_log import AuditLog
from app.models.mission import Mission
from app.models.plan import Plan
from app.models.user import User

logger = logging.getLogger("spectra.admin")

router = APIRouter()


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
