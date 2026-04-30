"""Admin audit log, dashboard statistics, and LLM usage endpoints."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.common import PaginatedResponse
from app.auth.rate_limit import RateLimits, limiter
from app.auth.rbac import Permission, require_permission
from app.core.config import settings
from app.core.database import get_async_session
from app.models.audit_log import AuditLog
from app.models.mission import Mission
from app.models.plan import Plan
from app.models.user import User
from app.repositories.audit_log import AuditLogRepository
from app.telemetry.telemetry import telemetry

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
    ip_address: str | None = Query(None, description="Filter by client IP address"),
    _user: User = require_permission(Permission.VIEW_AUDIT_LOG),
    session: AsyncSession = Depends(get_async_session),
) -> PaginatedResponse:
    repo = AuditLogRepository(session)
    parsed_date_from = datetime.fromisoformat(date_from).replace(tzinfo=UTC) if date_from else None
    parsed_date_to = datetime.fromisoformat(date_to).replace(tzinfo=UTC) if date_to else None
    offset = (page - 1) * per_page

    total = await repo.count_events(
        user_id=user_id,
        event_type=event_type,
        ip_address=ip_address,
        date_from=parsed_date_from,
        date_to=parsed_date_to,
    )
    rows = await repo.list_events(
        skip=offset,
        limit=per_page,
        user_id=user_id,
        event_type=event_type,
        ip_address=ip_address,
        date_from=parsed_date_from,
        date_to=parsed_date_to,
    )
    if not isinstance(total, int):
        total = len(rows)

    # Batch-fetch usernames for the page of audit log entries
    user_ids = {r.user_id for r in rows if r.user_id}
    username_map: dict[str, str] = {}
    if user_ids:
        try:
            user_rows = (await session.execute(
                select(User.id, User.username).where(User.id.in_(user_ids))
            )).all()
            username_map = {row[0]: row[1] for row in user_rows}
        except Exception:
            logger.debug("Could not resolve usernames for audit log entries", exc_info=True)

    items = [
        {
            "id": r.id,
            "user_id": r.user_id,
            "username": username_map.get(r.user_id) if r.user_id else None,
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
    except (OSError, RuntimeError):
        logger.debug("Failed to count missions for audit stats", exc_info=True)

    total_audit_events = (await session.execute(select(func.count()).select_from(AuditLog))).scalar() or 0

    role_result = await session.execute(select(User.role, func.count()).group_by(User.role))
    role_counts = dict.fromkeys(("admin", "staff", "user"), 0)
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
        "smtp_configured": settings.smtp_configured,
    }


@router.get("/api/admin/usage")
@limiter.limit(RateLimits.API_HEAVY)
async def admin_usage(
    request: Request,
    _user: User = require_permission(Permission.MANAGE_USERS),
) -> dict[str, Any]:
    """Return aggregated LLM usage stats from active cost trackers."""
    _ = request
    from spectra_ai.cost_tracker import get_cost_trackers

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
            missions.append(
                {
                    "mission_id": summary["mission_id"],
                    "agent_name": agent_name,
                    "role": agent_data["role"],
                    "calls": agent_data["calls"],
                    "tokens": agent_data["tokens"],
                    "cost_usd": agent_data["cost_usd"],
                    "avg_latency_ms": agent_data["avg_latency_ms"],
                    "errors": agent_data["errors"],
                }
            )

    return {
        "total_calls": grand_calls,
        "total_tokens": grand_tokens,
        "total_cost_usd": round(grand_cost, 6),
        "active_missions": saas.get("missions", {}).get("started", 0),
        "by_agent": missions,
    }
