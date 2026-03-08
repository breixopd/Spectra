"""
Observability API Router.

Provides endpoints for telemetry, metrics, and system health monitoring.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import get_current_active_user
from app.core.cache import get_cache
from app.core.circuit_breaker import circuit_breakers
from app.core.events import events
from app.core.telemetry import telemetry
from app.models.user import User

logger = logging.getLogger("spectra.api.observability")

router = APIRouter(prefix="/observability", tags=["Observability"])


@router.get("/stats")
async def get_observability_stats(
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
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
    except Exception:
        logger.warning("Cache unavailable for observability stats")

    return {
        "overview": telemetry.get_overview_stats(),
        "services": telemetry.get_service_health(),
        "traces": telemetry.get_traces(limit=100),
        "circuit_breakers": circuit_breakers.get_all_stats(),
        "events": [e.to_dict() for e in events.get_history(limit=100)],
        "cache": cache_stats,
        "cache_available": cache_available,
    }


@router.get("/traces")
async def get_traces(
    limit: int = Query(default=100, ge=1, le=500, description="Max traces to return"),
    status: str | None = Query(
        default=None, pattern="^(ok|error)$", description="Filter by status"
    ),
    _current_user: User = Depends(get_current_active_user),
) -> list[dict[str, Any]]:
    """Get recent traces with optional filtering."""
    return telemetry.get_traces(limit=min(limit, 500), status=status)


@router.get("/traces/{trace_id}")
async def get_trace_by_id(
    trace_id: str,
    _current_user: User = Depends(get_current_active_user),
) -> list[dict[str, Any]]:
    """Get all spans for a specific trace."""
    return telemetry.get_trace_by_id(trace_id)


@router.get("/slow-operations")
async def get_slow_operations(
    threshold_ms: float = 1000,
    limit: int = 20,
    _current_user: User = Depends(get_current_active_user),
) -> list[dict[str, Any]]:
    """Get slowest operations above threshold."""
    return telemetry.get_slow_operations(threshold_ms, limit)


@router.get("/errors")
async def get_error_traces(
    limit: int = 50,
    _current_user: User = Depends(get_current_active_user),
) -> list[dict[str, Any]]:
    """Get traces with errors."""
    return telemetry.get_error_traces(limit)


@router.get("/metrics")
async def get_metrics_summary(
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Get aggregated metrics summary."""
    return telemetry.get_metrics_summary()


@router.get("/services/health")
async def get_service_health(
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, dict[str, Any]]:
    """Get all service health statuses."""
    return telemetry.get_service_health()


@router.get("/circuit-breakers")
async def get_circuit_breakers(
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, dict[str, Any]]:
    """Get circuit breaker statuses."""
    return circuit_breakers.get_all_stats()


@router.post("/circuit-breakers/reset")
async def reset_circuit_breakers(
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, str]:
    """Reset all circuit breakers.

    Requires superuser privileges.
    """
    if not _current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Superuser access required")

    circuit_breakers.reset_all()
    return {"status": "ok", "message": "All circuit breakers reset"}


@router.get("/cache/stats")
async def get_cache_stats(
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Get cache statistics."""
    cache = get_cache()
    try:
        if not cache:
            return {"cache_available": False}
        stats = cache.get_stats()
        return {**stats, "cache_available": True}
    except Exception:
        logger.warning("Cache unavailable for stats endpoint")
        return {"cache_available": False}


@router.get("/events")
async def get_events(
    limit: int = Query(default=100, ge=1, le=500, description="Max events to return"),
    event_type: str | None = Query(
        default=None, max_length=50, description="Filter by event type"
    ),
    _current_user: User = Depends(get_current_active_user),
) -> list[dict[str, Any]]:
    """Get recent events."""
    return [
        e.to_dict()
        for e in events.get_history(event_type=event_type, limit=min(limit, 500))
    ]


@router.get("/events/stats")
async def get_event_stats(
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Get event statistics."""
    return events.get_stats()
