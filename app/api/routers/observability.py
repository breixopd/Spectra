"""
Observability API Router.

Provides endpoints for telemetry, metrics, and system health monitoring.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from spectra_common.constants import API_MAX_PAGE_SIZE, OBSERVABILITY_MAX_RESULTS
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import TypedDict

from app.auth.rate_limit import RateLimits, limiter
from app.auth.rbac import Permission, require_permission
from app.core.database import get_async_session
from app.infrastructure.cache import get_cache
from app.infrastructure.circuit_breaker import circuit_breakers
from app.infrastructure.events import events
from app.models.user import User
from app.services.system.health import collect_platform_health
from app.telemetry.telemetry import telemetry

logger = logging.getLogger(__name__)


class SystemStatsResponse(TypedDict):
    """Typed shape for the /stats endpoint response."""

    overview: dict[str, Any]
    services: dict[str, dict[str, Any]]
    traces: list[dict[str, Any]]
    circuit_breakers: dict[str, dict[str, Any]]
    events: list[dict[str, Any]]
    cache: dict[str, Any]
    cache_available: bool


router = APIRouter(prefix="/observability", tags=["Observability"])


@router.get("/stats")
@limiter.limit(RateLimits.OBSERVABILITY)
async def get_observability_stats(
    request: Request,
    _current_user: User = require_permission(Permission.MANAGE_SETTINGS),
) -> SystemStatsResponse:
    """
    Get comprehensive observability statistics.

    Returns telemetry, circuit breaker status, cache stats, and events.
    """
    cache = get_cache()
    cache_stats: dict[str, Any] = {}
    cache_available = False
    try:
        if cache:
            cache_stats = cache.get_stats() or {}
            cache_available = True
    except (OSError, RuntimeError, ValueError):
        logger.warning("Cache unavailable for observability stats")

    return {
        "overview": telemetry.get_overview_stats(),
        "services": telemetry.get_service_health(),
        "traces": telemetry.get_traces(limit=API_MAX_PAGE_SIZE),
        "circuit_breakers": circuit_breakers.get_all_stats(),
        "events": [e.to_dict() for e in events.get_history(limit=API_MAX_PAGE_SIZE)],
        "cache": cache_stats,
        "cache_available": cache_available,
    }


@router.get("/traces")
@limiter.limit(RateLimits.OBSERVABILITY)
async def get_traces(
    request: Request,
    limit: int = Query(
        default=API_MAX_PAGE_SIZE, ge=1, le=OBSERVABILITY_MAX_RESULTS, description="Max traces to return"
    ),
    status: str | None = Query(default=None, pattern="^(ok|error)$", description="Filter by status"),
    _current_user: User = require_permission(Permission.MANAGE_SETTINGS),
) -> list[dict[str, Any]]:
    """Get recent traces with optional filtering."""
    return telemetry.get_traces(limit=min(limit, OBSERVABILITY_MAX_RESULTS), status=status)


@router.get("/traces/{trace_id}")
@limiter.limit(RateLimits.OBSERVABILITY)
async def get_trace_by_id(
    request: Request,
    trace_id: str,
    _current_user: User = require_permission(Permission.MANAGE_SETTINGS),
) -> list[dict[str, Any]]:
    """Get all spans for a specific trace."""
    return telemetry.get_trace_by_id(trace_id)


@router.get("/slow-operations")
@limiter.limit(RateLimits.OBSERVABILITY)
async def get_slow_operations(
    request: Request,
    threshold_ms: float = 1000,
    limit: int = 20,
    _current_user: User = require_permission(Permission.MANAGE_SETTINGS),
) -> list[dict[str, Any]]:
    """Get slowest operations above threshold."""
    return telemetry.get_slow_operations(threshold_ms, limit)


@router.get("/errors")
@limiter.limit(RateLimits.OBSERVABILITY)
async def get_error_traces(
    request: Request,
    limit: int = 50,
    _current_user: User = require_permission(Permission.MANAGE_SETTINGS),
) -> list[dict[str, Any]]:
    """Get traces with errors."""
    return telemetry.get_error_traces(limit)


@router.get("/metrics")
@limiter.limit(RateLimits.OBSERVABILITY)
async def get_metrics_summary(
    request: Request,
    _current_user: User = require_permission(Permission.MANAGE_SETTINGS),
) -> dict[str, Any]:
    """Get aggregated metrics summary."""
    return telemetry.get_metrics_summary()


@router.get("/services/health")
@limiter.limit(RateLimits.OBSERVABILITY)
async def get_service_health(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = require_permission(Permission.MANAGE_SETTINGS),
) -> dict[str, Any]:
    """Get canonical service health plus telemetry's latest service status."""
    health = await collect_platform_health(db, detail="full", scope="services", include="nodes")
    return {
        "status": health["status"],
        "services": health["services"],
        "nodes": health["nodes"],
        "summary": health["summary"],
        "telemetry": telemetry.get_service_health(),
    }


@router.get("/circuit-breakers")
@limiter.limit(RateLimits.OBSERVABILITY)
async def get_circuit_breakers(
    request: Request,
    _current_user: User = require_permission(Permission.MANAGE_SETTINGS),
) -> dict[str, dict[str, Any]]:
    """Get circuit breaker statuses."""
    return circuit_breakers.get_all_stats()


@router.post("/circuit-breakers/reset")
@limiter.limit(RateLimits.OBSERVABILITY)
async def reset_circuit_breakers(
    request: Request,
    _current_user: User = require_permission(Permission.MANAGE_SETTINGS),
) -> dict[str, str]:
    """Reset all circuit breakers.

    Requires superuser privileges.
    """
    if not _current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Superuser access required")

    circuit_breakers.reset_all()
    return {"status": "ok", "message": "All circuit breakers reset"}


@router.get("/cache/stats")
@limiter.limit(RateLimits.OBSERVABILITY)
async def get_cache_stats(
    request: Request,
    _current_user: User = require_permission(Permission.MANAGE_SETTINGS),
) -> dict[str, Any]:
    """Get cache statistics."""
    cache = get_cache()
    try:
        if not cache:
            return {"cache_available": False}
        stats = cache.get_stats()
        return {**stats, "cache_available": True}
    except (OSError, RuntimeError, ValueError):
        logger.warning("Cache unavailable for stats endpoint")
        return {"cache_available": False}


@router.get("/events")
@limiter.limit(RateLimits.OBSERVABILITY)
async def get_events(
    request: Request,
    limit: int = Query(
        default=API_MAX_PAGE_SIZE, ge=1, le=OBSERVABILITY_MAX_RESULTS, description="Max events to return"
    ),
    offset: int = Query(default=0, ge=0, description="Skip this many events (cursor-based catch-up after reconnect)"),
    since: float | None = Query(default=None, description="Unix timestamp — only return events after this time"),
    event_type: str | None = Query(default=None, max_length=50, description="Filter by event type"),
    _current_user: User = require_permission(Permission.MANAGE_SETTINGS),
) -> list[dict[str, Any]]:
    """Get recent events. Use since/offset for catch-up after WebSocket reconnect."""
    return [
        e.to_dict()
        for e in events.get_history(
            event_type=event_type,
            limit=min(limit, OBSERVABILITY_MAX_RESULTS),
            since=since,
            offset=offset,
        )
    ]


@router.get("/events/stats")
@limiter.limit(RateLimits.OBSERVABILITY)
async def get_event_stats(
    request: Request,
    _current_user: User = require_permission(Permission.MANAGE_SETTINGS),
) -> dict[str, Any]:
    """Get event statistics."""
    return events.get_stats()


@router.get("/export/otlp")
@limiter.limit(RateLimits.OBSERVABILITY)
async def export_otlp(
    request: Request,
    _current_user: User = require_permission(Permission.MANAGE_SETTINGS),
) -> dict[str, Any]:
    """Export metrics and traces in OTLP JSON format for external collectors."""
    return telemetry.export_otlp_format()


@router.get("/metrics/history")
@limiter.limit(RateLimits.OBSERVABILITY)
async def get_metrics_history(
    request: Request,
    minutes: int = Query(default=60, ge=1, le=1440, description="Minutes of history"),
    _current_user: User = require_permission(Permission.MANAGE_SETTINGS),
) -> list[dict[str, Any]]:
    """Get historical metric snapshots for dashboards."""
    from app.infrastructure.metrics_store import get_metrics_store

    store = get_metrics_store()
    return store.get_history(minutes=minutes)


@router.get("/saas-metrics")
@limiter.limit(RateLimits.OBSERVABILITY)
async def get_saas_metrics(
    request: Request,
    _current_user: User = require_permission(Permission.MANAGE_SETTINGS),
) -> dict[str, Any]:
    """Get aggregated SaaS KPI metrics."""
    return telemetry.get_saas_metrics()
