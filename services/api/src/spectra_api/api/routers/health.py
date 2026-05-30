"""Canonical health check router."""

import hmac
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.params import Query as QueryParam
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_api.api.dependencies import (
    _decode_access_payload,
    _extract_request_token,
    _load_active_user_from_payload_with_session,
    get_current_active_user,
)
from spectra_common._meta.version import __version__
from spectra_common.config import get_settings as _get_settings
from spectra_persistence.database import get_async_session
from spectra_system.health import collect_platform_health, probe_http_health, readiness_from_health

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


def _latency_ms(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 1)


async def _get_health_user(request: Request, db: AsyncSession) -> Any | None:
    resolved_token, _source = _extract_request_token(request)
    payload = (await _decode_access_payload(resolved_token)) if resolved_token else None
    return await _load_active_user_from_payload_with_session(payload, db) if payload else None


def _has_internal_health_access(request: Request) -> bool:
    secret = _get_settings().SERVICE_AUTH_SECRET.get_secret_value()
    provided = request.headers.get("X-Service-Auth", "")
    return bool(secret and provided and hmac.compare_digest(provided, secret))


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


@router.get("/healthz", summary="Liveness probe")
async def liveness_check() -> dict[str, Any]:
    """Always returns 200 if the process is alive."""
    return {"status": "alive", "service": "spectra-api"}


@router.get(
    "/health/deep",
    summary="Deep health check",
    description="Functional checks for database, Redis, LLM, embeddings, S3, and sandbox. Requires admin or service auth.",
)
async def deep_health_check(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """Deep health performs real functional verification of every subsystem."""
    if not _has_internal_health_access(request):
        user = await _get_health_user(request, db)
        if not _is_admin_user(user):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Admin authentication required for deep health",
            )

    results: dict[str, Any] = {}
    overall = "healthy"

    start = time.monotonic()
    try:
        row = await db.execute(text("SELECT COUNT(*) FROM missions LIMIT 1"))
        count = row.scalar_one()
        results["database"] = {"status": "healthy", "latency_ms": _latency_ms(start), "missions_count": count}
    except Exception as exc:
        results["database"] = {"status": "unhealthy", "latency_ms": _latency_ms(start), "error": type(exc).__name__}
        overall = "degraded"

    start = time.monotonic()
    try:
        settings = _get_settings()
        redis_url = settings.REDIS_URL or settings.RATE_LIMIT_STORAGE
        if redis_url and redis_url.startswith(("redis://", "rediss://")):
            import redis.asyncio as aioredis

            r = aioredis.from_url(redis_url, socket_timeout=2)
            probe_key = f"health:deep:{uuid.uuid4().hex}"
            await r.set(probe_key, "ok", ex=10)
            val = await r.get(probe_key)
            await r.delete(probe_key)
            await r.aclose()
            if val == b"ok":
                results["redis"] = {"status": "healthy", "latency_ms": _latency_ms(start)}
            else:
                results["redis"] = {"status": "degraded", "latency_ms": _latency_ms(start), "error": "read mismatch"}
                overall = "degraded"
        else:
            results["redis"] = {"status": "not_configured", "latency_ms": _latency_ms(start)}
    except Exception as exc:
        results["redis"] = {"status": "unhealthy", "latency_ms": _latency_ms(start), "error": type(exc).__name__}
        overall = "degraded"

    start = time.monotonic()
    try:
        from spectra_ai_core.gateway.ai_gateway import get_ai_gateway

        gw = get_ai_gateway()
        chat_resp = await gw.chat([{"role": "user", "content": "say ok"}], tier=1, max_tokens=1)
        content = chat_resp.get("content", "")
        if content:
            results["llm"] = {"status": "healthy", "latency_ms": _latency_ms(start), "response": content[:50]}
        else:
            results["llm"] = {"status": "degraded", "latency_ms": _latency_ms(start), "error": "empty response"}
            overall = "degraded"
    except Exception as exc:
        results["llm"] = {"status": "unhealthy", "latency_ms": _latency_ms(start), "error": type(exc).__name__}
        overall = "degraded"

    start = time.monotonic()
    try:
        from spectra_ai_core.embeddings import EmbeddingService

        svc = EmbeddingService()
        await svc._load_model()
        embedding = await svc.embed("health probe")
        dim = len(embedding)
        if dim > 0:
            results["embeddings"] = {"status": "healthy", "latency_ms": _latency_ms(start), "dimensions": dim}
        else:
            results["embeddings"] = {"status": "degraded", "latency_ms": _latency_ms(start), "error": "zero dimensions"}
            overall = "degraded"
    except Exception as exc:
        results["embeddings"] = {"status": "unhealthy", "latency_ms": _latency_ms(start), "error": type(exc).__name__}
        overall = "degraded"

    start = time.monotonic()
    try:
        from spectra_storage_policy.storage import get_storage_service

        storage = get_storage_service()
        bucket = _get_settings().S3_BUCKET_MISSIONS
        probe_key = f"health/deep/{uuid.uuid4().hex}"
        probe_data = b"spectra-deep-health"
        await storage.upload(bucket, probe_key, probe_data)
        downloaded = await storage.download(bucket, probe_key)
        await storage.delete(bucket, probe_key)
        if downloaded == probe_data:
            results["s3"] = {"status": "healthy", "latency_ms": _latency_ms(start)}
        else:
            results["s3"] = {"status": "degraded", "latency_ms": _latency_ms(start), "error": "data mismatch"}
            overall = "degraded"
    except Exception as exc:
        results["s3"] = {"status": "unhealthy", "latency_ms": _latency_ms(start), "error": type(exc).__name__}
        overall = "degraded"

    start = time.monotonic()
    try:
        from spectra_tools.sandbox import get_sandbox_pool

        pool = get_sandbox_pool()
        if pool and pool.available:
            import docker

            client = docker.from_env()
            client.ping()
            image_name = _get_settings().SANDBOX_IMAGE
            try:
                client.images.get(image_name)
                image_ok = True
            except Exception:
                image_ok = False
            client.close()
            if image_ok:
                results["sandbox"] = {"status": "healthy", "latency_ms": _latency_ms(start), "image": image_name}
            else:
                results["sandbox"] = {"status": "degraded", "latency_ms": _latency_ms(start), "error": f"image {image_name} not found"}
                overall = "degraded"
        else:
            results["sandbox"] = {"status": "not_configured", "latency_ms": _latency_ms(start), "error": "Docker unavailable"}
    except Exception as exc:
        results["sandbox"] = {"status": "unhealthy", "latency_ms": _latency_ms(start), "error": type(exc).__name__}
        overall = "degraded"

    if overall != "healthy":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": overall,
        "service": "app",
        "timestamp": datetime.now(UTC).isoformat(),
        "checks": results,
    }


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
