"""Admin monitoring, metrics trends, and data export endpoints."""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Permission, require_permission
from app.core.database import get_async_session
from app.infrastructure.metrics_store import get_metrics_store
from app.models.mission import Mission
from app.models.user import User
from app.telemetry.telemetry import telemetry

logger = logging.getLogger(__name__)

router = APIRouter()


def _cost_summary(cost_trackers: dict) -> dict[str, Any]:
    """Aggregate cost/token/call totals from all active trackers."""
    total_cost = 0.0
    total_tokens = 0
    total_calls = 0
    for tracker in cost_trackers.values():
        summary = tracker.get_summary()
        total_cost += summary["total_cost_usd"]
        total_tokens += summary["total_tokens"]
        total_calls += summary["total_calls"]
    return {
        "total_cost_usd": round(total_cost, 4),
        "total_tokens": total_tokens,
        "total_calls": total_calls,
    }


@router.get("/api/v1/admin/monitoring/overview")
async def monitoring_overview(
    _user: User = require_permission(Permission.VIEW_MONITORING),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """System-wide monitoring overview with key metrics."""
    metrics_store = get_metrics_store()
    overview = telemetry.get_overview_stats()
    service_health = telemetry.get_service_health()

    now = datetime.now(UTC)
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)

    missions_24h = 0
    missions_7d = 0
    try:
        missions_24h = (
            await session.execute(select(func.count()).select_from(Mission).where(Mission.created_at >= day_ago))
        ).scalar() or 0
        missions_7d = (
            await session.execute(select(func.count()).select_from(Mission).where(Mission.created_at >= week_ago))
        ).scalar() or 0
    except (OSError, RuntimeError):
        pass

    from app.services.ai.cost_tracker import get_cost_trackers

    cost_trackers = get_cost_trackers()
    llm = _cost_summary(cost_trackers) if cost_trackers else {"total_cost_usd": 0, "total_tokens": 0, "total_calls": 0}

    return {
        "system": overview,
        "services": service_health,
        "missions": {
            "last_24h": missions_24h,
            "last_7d": missions_7d,
        },
        "llm": llm,
        "metrics_history_available": len(metrics_store.get_history(minutes=60)) > 0,
    }


@router.get("/api/v1/admin/monitoring/trends")
async def monitoring_trends(
    minutes: int = Query(60, ge=5, le=1440, description="Time window in minutes"),
    _user: User = require_permission(Permission.VIEW_MONITORING),
) -> dict[str, Any]:
    """Get metrics trends over the specified time window."""
    metrics_store = get_metrics_store()
    history = metrics_store.get_history(minutes=minutes)
    return {
        "window_minutes": minutes,
        "data_points": len(history),
        "history": history,
    }


@router.get("/api/v1/admin/monitoring/export")
async def export_metrics(
    format: str = Query("json", pattern="^(json|csv)$"),
    minutes: int = Query(60, ge=5, le=10080),
    _user: User = require_permission(Permission.VIEW_MONITORING),
) -> StreamingResponse:
    """Export metrics data as JSON or CSV for external analysis."""
    metrics_store = get_metrics_store()
    history = metrics_store.get_history(minutes=minutes)

    if format == "csv":
        output = io.StringIO()
        if history:
            writer = csv.DictWriter(output, fieldnames=list(history[0].keys()))
            writer.writeheader()
            writer.writerows(history)
        content = output.getvalue()
        return StreamingResponse(
            iter([content]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=spectra_metrics_{minutes}m.csv"},
        )

    content = json.dumps({"window_minutes": minutes, "data": history}, default=str)
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=spectra_metrics_{minutes}m.json"},
    )


@router.get("/api/v1/admin/monitoring/llm-usage")
async def llm_usage_breakdown(
    _user: User = require_permission(Permission.VIEW_MONITORING),
) -> dict[str, Any]:
    """Detailed LLM usage breakdown by mission/tracker."""
    from app.services.ai.cost_tracker import get_cost_trackers

    cost_trackers = get_cost_trackers()
    breakdown = {}
    for name, tracker in (cost_trackers or {}).items():
        summary = tracker.get_summary()
        breakdown[name] = {
            "total_cost_usd": summary["total_cost_usd"],
            "total_tokens": summary["total_tokens"],
            "total_calls": summary["total_calls"],
            "avg_tokens_per_call": round(summary["total_tokens"] / max(summary["total_calls"], 1), 1),
            "duration_seconds": summary.get("duration_seconds"),
        }

    agg = _cost_summary(cost_trackers) if cost_trackers else {"total_cost_usd": 0, "total_tokens": 0, "total_calls": 0}
    return {
        "breakdown": breakdown,
        "summary": agg,
    }
