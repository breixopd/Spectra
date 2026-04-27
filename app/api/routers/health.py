"""Canonical health check router."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.params import Query as QueryParam
from sqlalchemy.ext.asyncio import AsyncSession

from app._meta.version import __version__
from app.api.dependencies import (
    _decode_access_payload,
    _extract_request_token,
    _load_active_user_from_payload_with_session,
    get_current_active_user,
)
from app.core.config import get_settings as _get_settings
from app.core.database import get_async_session
from app.services.system.health import collect_platform_health, probe_http_health, readiness_from_health

logger = logging.getLogger(__name__)

router = APIRouter()


async def _probe_http_health(url: str, *, path: str) -> bool:
    result = await probe_http_health(url, path=path)
    return result.get("status") == "healthy"


@router.get("/version", summary="Application version")
async def get_version(
    _current_user: Any = Depends(get_current_active_user),
):
    return {"version": __version__}


def _data_dir() -> str:
    return "/app/data"


async def _get_health_user(request: Request, db: AsyncSession) -> Any | None:
    resolved_token, _source = _extract_request_token(request)
    payload = (await _decode_access_payload(resolved_token)) if resolved_token else None
    return await _load_active_user_from_payload_with_session(payload, db) if payload else None


def _has_internal_health_access(request: Request) -> bool:
    secret = _get_settings().SERVICE_AUTH_SECRET.get_secret_value()
    provided = request.headers.get("X-Service-Auth", "")
    return bool(secret and provided and provided == secret)


def _is_admin_user(user: Any | None) -> bool:
    return bool(user and (getattr(user, "is_superuser", False) or getattr(user, "role", "") == "admin"))


def _query_default(value: Any, fallback: Any) -> Any:
    return fallback if isinstance(value, QueryParam) else value


@router.get(
    "/health",
    summary="Health check",
    description="Liveness and readiness probe. Returns 200 if healthy, 503 if degraded. Use ?verbose=true for component details.",
)
async def health_check(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_async_session),
    verbose: bool = Query(False, description="Include detailed component status"),
    detail: str = Query("basic", pattern="^(basic|full|verbose|detailed)$", description="Health detail level"),
    scope: str = Query("platform", pattern="^(platform|services|nodes|public|ready)$", description="Health scope"),
    include: str | None = Query(None, description="Comma-separated optional sections, e.g. services,nodes"),
    service: str | None = Query(None, description="Limit service details to one service key"),
) -> dict[str, Any]:
    """Canonical health endpoint.

    Basic detail is public. Full detail requires an admin user or the
    internal service-auth header.
    """
    verbose_enabled = _query_default(verbose, False) is True
    requested_detail = "full" if verbose_enabled else _query_default(detail, "basic")
    scope = _query_default(scope, "platform")
    include = _query_default(include, None)
    service = _query_default(service, None)
    wants_full = requested_detail in {"full", "verbose", "detailed"}
    if wants_full and not _has_internal_health_access(request):
        user = await _get_health_user(request, db)
        if not _is_admin_user(user):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Admin authentication required for full health details",
            )

    health_status = await collect_platform_health(
        db,
        detail=requested_detail,
        scope=scope,
        include=include,
        service=service,
    )

    if health_status.get("status") != "healthy":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return health_status


@router.get(
    "/health/ready",
    summary="Readiness probe",
    description="Check if the database, AI service, TensorZero, scheduler, worker, LLM, and embeddings are ready to serve traffic. Returns 503 if any is not ready.",
)
async def readiness_check(
    response: Response,
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """Readiness compatibility endpoint backed by canonical health."""
    health = await collect_platform_health(db, detail="full", scope="ready")
    checks = readiness_from_health(health)
    all_ready = all(checks.values())
    result = {
        "ready": all_ready,
        "checks": checks,
        "status": "healthy" if all_ready else "degraded",
    }

    if not all_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return result


@router.get(
    "/health/services",
    summary="Aggregate service health",
    description="Health of all backend services across replicas. Requires authentication.",
)
async def service_health(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """Health of backend services and scaled nodes. Requires admin or service auth."""
    if not _has_internal_health_access(request):
        user = await _get_health_user(request, db)
        if not _is_admin_user(user):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin authentication required")

    health = await collect_platform_health(db, detail="full", scope="services", include="nodes")
    if health.get("status") != "healthy":
        # Keep the aggregate endpoint informative; callers can inspect details.
        logger.debug("Aggregate service health degraded: %s", health.get("summary"))
    return {
        "status": health["status"],
        "services": health["services"],
        "nodes": health["nodes"],
        "instance": health["instance"],
        "timestamp": health["timestamp"],
        "summary": health["summary"],
    }
