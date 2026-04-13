"""
Health check router.

Provides /api/health for liveness and readiness probes.
Unauthenticated for load balancer/orchestrator use.
"""

import logging
import os
import shutil
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    _decode_access_payload,
    _extract_request_token,
    _load_active_user_from_payload_with_session,
)
from app.core.config import get_settings as _get_settings
from app.core.database import get_async_session
from app.version import __version__

logger = logging.getLogger(__name__)

router = APIRouter()


async def _probe_http_health(url: str, *, path: str) -> bool:
    if not url:
        return False

    try:
        import httpx
    except ImportError:
        logger.debug("Health check: httpx unavailable for %s%s", url, path)
        return False

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{url.rstrip('/')}{path}")
        return response.status_code == status.HTTP_200_OK
    except Exception:
        logger.debug("Health check: HTTP probe failed for %s%s", url, path, exc_info=True)
        return False


@router.get("/version", summary="Application version")
async def get_version():
    return {"version": __version__}


def _data_dir() -> str:
    return "/app/data"


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
) -> dict[str, Any]:
    """
    Comprehensive health check endpoint.

    Returns 200 if core services (database) are healthy.
    Returns 503 if any critical service is down.

    Use ?verbose=true for detailed component status including RAG, LLM, cache, disk.
    """
    health_status: dict = {
        "status": "healthy",
        "service": "spectra",
        "version": __version__,
        "components": {
            "database": "unknown",
        },
    }
    is_healthy = True

    # Check Database (critical) — measure latency
    try:
        t0 = time.monotonic()
        await db.execute(text("SELECT 1"))
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        health_status["components"]["database"] = {
            "status": "healthy",
            "latency_ms": latency_ms,
        }
    except (OSError, SQLAlchemyError) as e:
        health_status["components"]["database"] = {
            "status": "unhealthy",
            "error": type(e).__name__,
        }
        is_healthy = False

    # Check Redis (critical for rate limiting / caching)
    try:
        import redis.asyncio as aioredis

        settings = _get_settings()
        redis_url = settings.RATE_LIMIT_STORAGE
        if redis_url and redis_url.startswith(("redis://", "rediss://")):
            r = aioredis.from_url(redis_url, socket_timeout=2)
            await r.ping()
            await r.aclose()
            health_status["components"]["redis"] = {"status": "healthy"}
        else:
            health_status["components"]["redis"] = {"status": "not configured"}
    except Exception as e:
        health_status["components"]["redis"] = {"status": "unhealthy", "error": type(e).__name__}
        is_healthy = False

    # Check S3/Garage storage
    try:
        from app.services.storage import get_storage_service

        storage = get_storage_service()
        s3_health = await storage.health_check()
        health_status["components"]["s3"] = {
            "status": s3_health.get("status", "unknown"),
        }
        if s3_health.get("status") != "healthy":
            is_healthy = False
    except Exception as e:
        health_status["components"]["s3"] = {"status": "unhealthy", "error": type(e).__name__}
        is_healthy = False

    if verbose:
        resolved_token, _source = _extract_request_token(request)
        payload = (await _decode_access_payload(resolved_token)) if resolved_token else None
        user = await _load_active_user_from_payload_with_session(payload, db) if payload else None
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required for verbose health details"
            )

        # Check RAG/Embedding service
        try:
            from app.services.gateway.ai_gateway import get_ai_gateway

            gw = get_ai_gateway()
            emb = await gw.check_embeddings_status()
            if emb["functional"]:
                health_status["components"]["embeddings"] = "healthy"
            elif emb["status"] == "fallback":
                health_status["components"]["embeddings"] = "degraded: using fallback (no semantic search)"
            else:
                health_status["components"]["embeddings"] = emb["status"]
        except (OSError, RuntimeError, ValueError) as e:
            health_status["components"]["embeddings"] = f"unavailable: {type(e).__name__}"

        # Check LLM provider
        try:
            from app.services.gateway.ai_gateway import get_ai_gateway as _get_gw

            gw = _get_gw()
            llm = await gw.check_llm_status()
            health_status["components"]["llm"] = llm["status"]
        except (OSError, RuntimeError, ValueError) as e:
            health_status["components"]["llm"] = f"unavailable: {type(e).__name__}"

        # Check cache
        try:
            from app.core.cache import get_cache

            cache = get_cache()
            if cache:
                stats = cache.get_stats()
                health_status["components"]["cache"] = {
                    "status": "healthy",
                    "hit_rate_percent": stats.get("hit_rate_percent", 0),
                }
            else:
                health_status["components"]["cache"] = {"status": "unavailable"}
        except (OSError, ConnectionError, TimeoutError) as e:
            health_status["components"]["cache"] = {"status": "error", "error": type(e).__name__}

        # Check worker / sandbox pool
        try:
            from app.services.tools.sandbox import get_sandbox_pool

            pool = get_sandbox_pool()
            if pool and pool.available:
                health_status["components"]["sandbox_pool"] = "healthy"
            elif pool:
                health_status["components"]["sandbox_pool"] = "unavailable: Docker not accessible"
            else:
                health_status["components"]["sandbox_pool"] = "not initialized"
        except (OSError, RuntimeError, ValueError) as e:
            health_status["components"]["sandbox_pool"] = f"error: {type(e).__name__}"

        # Disk space for data directory
        try:
            usage = shutil.disk_usage(_data_dir())
            free_gb = round(usage.free / (1024**3), 2)
            total_gb = round(usage.total / (1024**3), 2)
            used_pct = round(usage.used / usage.total * 100, 1)
            disk_status = "healthy" if used_pct < 90 else "warning: low disk space"
            health_status["components"]["disk"] = {
                "status": disk_status,
                "free_gb": free_gb,
                "total_gb": total_gb,
                "used_percent": used_pct,
            }
        except (OSError, RuntimeError, ValueError) as e:
            health_status["components"]["disk"] = {"status": "error", "error": type(e).__name__}

        # Check TensorZero gateway
        try:
            import httpx

            tz_url = getattr(_get_settings(), "TENSORZERO_GATEWAY_URL", "")
            if tz_url:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    tz_resp = await client.get(f"{tz_url.rstrip('/')}/health")
                    health_status["components"]["tensorzero"] = {
                        "status": "healthy" if tz_resp.status_code == 200 else "degraded",
                    }
            else:
                health_status["components"]["tensorzero"] = {"status": "not configured"}
        except Exception as e:
            health_status["components"]["tensorzero"] = {"status": "unreachable", "error": type(e).__name__}

    if not is_healthy:
        health_status["status"] = "degraded"
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
    """
    Readiness probe - checks if ALL components are ready to serve traffic.
    Returns 503 if any component is not ready.
    """
    settings = _get_settings()
    checks = {
        "database": False,
        "llm": False,
        "embeddings": False,
        "ai_service": False,
        "tensorzero": False,
        "scheduler": False,
        "worker": False,
    }

    # Database
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = True
    except (OSError, SQLAlchemyError):
        logger.debug("Health check: database unavailable", exc_info=True)

    # LLM
    try:
        from app.services.gateway.ai_gateway import get_ai_gateway

        gw = get_ai_gateway()
        llm = await gw.check_llm_status()
        checks["llm"] = llm["available"]
    except (OSError, RuntimeError, ValueError):
        logger.debug("Health check: LLM unavailable", exc_info=True)

    # Embeddings
    try:
        from app.services.gateway.ai_gateway import get_ai_gateway as _get_gw

        gw = _get_gw()
        emb = await gw.check_embeddings_status()
        checks["embeddings"] = emb["functional"]
    except (OSError, RuntimeError, ValueError):
        logger.debug("Health check: embeddings unavailable", exc_info=True)

    checks["ai_service"] = await _probe_http_health(settings.AI_SERVICE_URL, path="/health")
    if not checks["ai_service"]:
        logger.debug("Health check: AI service unavailable")

    checks["tensorzero"] = await _probe_http_health(
        getattr(settings, "TENSORZERO_GATEWAY_URL", ""),
        path="/health",
    )
    if not checks["tensorzero"]:
        logger.debug("Health check: TensorZero unavailable")

    checks["scheduler"] = await _probe_http_health(settings.SCHEDULER_SERVICE_URL, path="/health")
    if not checks["scheduler"]:
        logger.debug("Health check: scheduler unavailable")

    checks["worker"] = await _probe_http_health(settings.WORKER_SERVICE_URL, path="/health")
    if not checks["worker"]:
        logger.debug("Health check: worker unavailable")

    all_ready = all(checks.values())
    result = {
        "ready": all_ready,
        "checks": checks,
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
    """Health of all backend services. Requires authentication."""
    resolved_token, _source = _extract_request_token(request)
    payload = (await _decode_access_payload(resolved_token)) if resolved_token else None
    user = await _load_active_user_from_payload_with_session(payload, db) if payload else None
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    try:
        import httpx
    except ImportError:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="httpx not available")

    settings = _get_settings()
    services: dict[str, Any] = {}

    # Check AI service
    ai_url = settings.AI_SERVICE_URL
    if ai_url:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{ai_url.rstrip('/')}/api/health")
                services["ai_service"] = {"status": "healthy" if r.status_code == 200 else "degraded", "url": ai_url}
        except Exception as e:
            services["ai_service"] = {"status": "unreachable", "error": type(e).__name__}

    # Check TensorZero
    tz_url = getattr(settings, "TENSORZERO_GATEWAY_URL", "")
    if tz_url:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{tz_url.rstrip('/')}/health")
                services["tensorzero"] = {"status": "healthy" if r.status_code == 200 else "degraded"}
        except Exception as e:
            services["tensorzero"] = {"status": "unreachable", "error": type(e).__name__}

    # Check Scheduler
    scheduler_url = settings.SCHEDULER_SERVICE_URL
    if scheduler_url:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{scheduler_url.rstrip('/')}/api/health")
                services["scheduler"] = {"status": "healthy" if r.status_code == 200 else "degraded"}
        except Exception as e:
            services["scheduler"] = {"status": "unreachable", "error": type(e).__name__}

    # Check Worker
    worker_url = settings.WORKER_SERVICE_URL
    if worker_url:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{worker_url.rstrip('/')}/api/health")
                services["worker"] = {"status": "healthy" if r.status_code == 200 else "degraded"}
        except Exception as e:
            services["worker"] = {"status": "unreachable", "error": type(e).__name__}

    return {
        "status": "healthy" if all(s.get("status") == "healthy" for s in services.values()) else "degraded",
        "services": services,
        "instance": os.environ.get("HOSTNAME", "unknown"),
    }
