"""Admin metrics, cost tracking, and usage statistics endpoints."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.rbac import Permission, require_permission
from app.models.user import User

logger = logging.getLogger("spectra.admin.metrics")

router = APIRouter()


@router.get("/api/admin/metrics")
async def get_admin_metrics(
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
) -> dict:
    """Get real-time system metrics from telemetry and metrics store."""
    from app.core.metrics_store import get_metrics_store
    from app.core.telemetry import telemetry

    summary = telemetry.get_metrics_summary()
    counters = summary.get("counters", {})
    histograms = summary.get("histograms", {})
    overview = telemetry.get_overview_stats()

    metrics_store = get_metrics_store()

    # Helper: sum counter values across all label combinations
    def _sum_counter(prefix: str) -> float:
        return sum(v for k, v in counters.items() if k.startswith(prefix))

    # Helper: get histogram stats for a given metric name prefix
    def _histogram_stats(prefix: str) -> dict:
        for k, v in histograms.items():
            if k.startswith(prefix):
                return v
        return {}

    return {
        "llm": {
            "total_calls": _sum_counter("llm_calls_total"),
            "total_tokens": _sum_counter("llm_tokens_total"),
            "total_errors": _sum_counter("llm_errors_total"),
            "duration_stats": _histogram_stats("llm_duration_ms"),
        },
        "tools": {
            "total_executions": _sum_counter("tool_executions_total"),
            "total_errors": _sum_counter("tool_errors_total"),
            "duration_stats": _histogram_stats("tool_duration_ms"),
        },
        "http": {
            "total_requests": overview.get("total_requests", 0),
            "total_errors": overview.get("total_errors", 0),
            "error_rate_percent": overview.get("error_rate_percent", 0),
            "avg_latency_ms": overview.get("avg_latency_ms", 0),
            "latency_percentiles": overview.get("latency_percentiles", {}),
        },
        "missions": {
            "total_events": _sum_counter("mission_events_total"),
        },
        "services": telemetry.get_service_health(),
        "history": metrics_store.get_history(minutes=60),
    }


@router.get("/api/admin/metrics/history")
async def get_metrics_history(
    hours: int = Query(default=24, ge=1, le=168),
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
) -> list[dict]:
    """Return time-series metrics history from the in-memory metrics store."""
    from app.core.metrics_store import get_metrics_store

    store = get_metrics_store()
    return store.get_history(minutes=hours * 60)


@router.get("/api/admin/cost-summary")
async def get_cost_summary(
    days: int = Query(default=30, ge=1, le=365),
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    """Aggregate LLM cost data from mission summaries."""
    from app.models.mission import Mission

    cutoff = datetime.now(UTC) - timedelta(days=days)

    # Fetch completed missions with summary data within the time range
    stmt = (
        select(Mission)
        .where(
            Mission.created_at >= cutoff,
            Mission.summary.isnot(None),
        )
        .order_by(Mission.created_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()

    total_cost = 0.0
    total_tokens = 0
    total_calls = 0
    by_agent: dict[str, dict] = {}
    daily_costs: dict[str, float] = {}

    for m in rows:
        cost_data = (m.summary or {}).get("cost_data")
        if not cost_data:
            continue

        mission_cost = cost_data.get("total_cost_usd", 0)
        mission_tokens = cost_data.get("total_tokens", 0)
        mission_calls = cost_data.get("total_calls", 0)

        total_cost += mission_cost
        total_tokens += mission_tokens
        total_calls += mission_calls

        # Aggregate per-agent data
        for agent_name, agent_info in cost_data.get("by_agent", {}).items():
            if agent_name not in by_agent:
                by_agent[agent_name] = {
                    "calls": 0,
                    "tokens": 0,
                    "cost_usd": 0.0,
                    "errors": 0,
                }
            by_agent[agent_name]["calls"] += agent_info.get("calls", 0)
            by_agent[agent_name]["tokens"] += agent_info.get("tokens", 0)
            by_agent[agent_name]["cost_usd"] += agent_info.get("cost_usd", 0)
            by_agent[agent_name]["errors"] += agent_info.get("errors", 0)

        # Daily cost aggregation
        day_key = m.created_at.strftime("%Y-%m-%d") if m.created_at else "unknown"
        daily_costs[day_key] = daily_costs.get(day_key, 0) + mission_cost

    return {
        "period_days": days,
        "total_cost_usd": round(total_cost, 6),
        "total_tokens": total_tokens,
        "total_calls": total_calls,
        "missions_with_cost_data": sum(1 for m in rows if (m.summary or {}).get("cost_data")),
        "by_agent": {
            name: {k: round(v, 6) if isinstance(v, float) else v for k, v in info.items()}
            for name, info in by_agent.items()
        },
        "daily_costs": [{"date": d, "cost_usd": round(c, 6)} for d, c in sorted(daily_costs.items())],
    }


@router.get("/api/admin/usage-stats")
async def get_usage_stats(
    days: int = Query(default=30, ge=1, le=365),
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    """Return usage statistics per user aggregated from UsageRecord."""
    from app.models.plan import UsageRecord

    cutoff = datetime.now(UTC) - timedelta(days=days)

    stmt = select(UsageRecord).where(UsageRecord.period_start >= cutoff)
    rows = (await session.execute(stmt)).scalars().all()

    per_user: dict[str, dict] = {}
    totals = {
        "api_requests": 0,
        "missions_started": 0,
        "sandbox_minutes": 0,
        "llm_tokens_used": 0,
    }

    for r in rows:
        uid = r.user_id
        if uid not in per_user:
            per_user[uid] = {
                "api_requests": 0,
                "missions_started": 0,
                "sandbox_minutes": 0,
                "llm_tokens_used": 0,
            }
        per_user[uid]["api_requests"] += r.api_requests
        per_user[uid]["missions_started"] += r.missions_started
        per_user[uid]["sandbox_minutes"] += r.sandbox_minutes
        per_user[uid]["llm_tokens_used"] += r.llm_tokens_used

        totals["api_requests"] += r.api_requests
        totals["missions_started"] += r.missions_started
        totals["sandbox_minutes"] += r.sandbox_minutes
        totals["llm_tokens_used"] += r.llm_tokens_used

    return {
        "period_days": days,
        "totals": totals,
        "per_user": per_user,
        "unique_users": len(per_user),
    }
