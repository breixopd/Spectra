"""Admin audit log, dashboard statistics, and LLM usage endpoints."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import PaginatedResponse
from app.core.config import settings
from app.core.database import get_async_session
from app.core.rbac import Permission, require_permission
from app.core.telemetry import telemetry
from app.models.audit_log import AuditLog
from app.models.mission import Mission
from app.models.plan import Plan
from app.models.user import User
from app.services.ai.cost_tracker import get_cost_trackers

logger = logging.getLogger(__name__)

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
    total_users = (await session.execute(select(func.count()).select_from(User))).scalar() or 0
    active_users = (
        await session.execute(select(func.count()).select_from(User).where(User.is_active.is_(True)))
    ).scalar() or 0

    total_plans = (await session.execute(select(func.count()).select_from(Plan))).scalar() or 0

    total_missions = 0
    try:
        total_missions = (await session.execute(select(func.count()).select_from(Mission))).scalar() or 0
    except Exception:
        logger.debug("Failed to count missions for audit stats", exc_info=True)

    total_audit_events = (await session.execute(select(func.count()).select_from(AuditLog))).scalar() or 0

    role_result = await session.execute(select(User.role, func.count()).group_by(User.role))
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
        "smtp_host": settings.SMTP_HOST or "",
    }


@router.get("/api/admin/usage")
async def admin_usage(
    _user: User = require_permission(Permission.MANAGE_USERS),
) -> dict[str, Any]:
    """Return aggregated LLM usage stats from active cost trackers."""
    trackers = get_cost_trackers()
    saas = telemetry.get_saas_metrics()

    missions: list[dict[str, Any]] = []
    grand_tokens = 0
    grand_cost = 0.0
    grand_calls = 0

    for _mid, tracker in trackers.items():
        summary = tracker.get_summary()
        grand_tokens += summary["total_tokens"]
        grand_cost += summary["total_cost_usd"]
        grand_calls += summary["total_calls"]

        for agent_name, agent_data in summary.get("by_agent", {}).items():
            missions.append({
                "mission_id": summary["mission_id"],
                "agent_name": agent_name,
                "role": agent_data["role"],
                "calls": agent_data["calls"],
                "tokens": agent_data["tokens"],
                "cost_usd": agent_data["cost_usd"],
                "avg_latency_ms": agent_data["avg_latency_ms"],
                "errors": agent_data["errors"],
            })

    return {
        "total_calls": grand_calls,
        "total_tokens": grand_tokens,
        "total_cost_usd": round(grand_cost, 6),
        "active_missions": saas.get("missions", {}).get("started", 0),
        "by_agent": missions,
    }
