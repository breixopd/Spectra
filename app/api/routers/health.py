"""
Health check router.

Provides /api/health for liveness and readiness probes.
Unauthenticated for load balancer/orchestrator use.
"""

import logging
import shutil
import time

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.version import __version__

logger = logging.getLogger("spectra.health")

router = APIRouter()

DATA_DIR = "/app/data"


@router.get(
    "/health",
    summary="Health check",
    description="Liveness and readiness probe. Returns 200 if healthy, 503 if degraded. Use ?verbose=true for component details.",
)
async def health_check(
    response: Response,
    db: AsyncSession = Depends(get_async_session),
    verbose: bool = Query(False, description="Include detailed component status"),
):
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
    except Exception as e:
        health_status["components"]["database"] = {
            "status": "unhealthy",
            "error": type(e).__name__,
        }
        is_healthy = False

    if verbose:
        # Check RAG/Embedding service
        try:
            from app.services.ai.rag import RAGService

            rag = RAGService()
            if rag.is_functional:
                health_status["components"]["embeddings"] = "healthy"
            else:
                health_status["components"]["embeddings"] = "degraded: using fallback (no semantic search)"
        except Exception as e:
            health_status["components"]["embeddings"] = f"unavailable: {type(e).__name__}"

        # Check LLM provider
        try:
            from app.services.ai.router import get_smart_router

            router_instance = get_smart_router()
            provider = getattr(router_instance, "provider", "unknown")
            health_status["components"]["llm"] = f"configured: {provider}"
        except Exception as e:
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
        except Exception as e:
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
        except Exception as e:
            health_status["components"]["sandbox_pool"] = f"error: {type(e).__name__}"

        # Disk space for data directory
        try:
            usage = shutil.disk_usage(DATA_DIR)
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
        except Exception as e:
            health_status["components"]["disk"] = {"status": "error", "error": type(e).__name__}

    if not is_healthy:
        health_status["status"] = "degraded"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return health_status


@router.get(
    "/health/ready",
    summary="Readiness probe",
    description="Check if all components (database, LLM, embeddings) are ready to serve traffic. Returns 503 if any is not ready.",
)
async def readiness_check(
    response: Response,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Readiness probe - checks if ALL components are ready to serve traffic.
    Returns 503 if any component is not ready.
    """
    checks = {"database": False, "llm": False, "embeddings": False}

    # Database
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        logger.debug("Health check: database unavailable", exc_info=True)

    # LLM
    try:
        from app.services.ai.router import get_smart_router

        router_instance = get_smart_router()
        checks["llm"] = router_instance is not None
    except Exception:
        logger.debug("Health check: LLM unavailable", exc_info=True)

    # Embeddings
    try:
        from app.services.ai.rag import RAGService

        rag = RAGService()
        checks["embeddings"] = rag.is_functional
    except Exception:
        logger.debug("Health check: embeddings unavailable", exc_info=True)

    all_ready = all(checks.values())
    result = {
        "ready": all_ready,
        "checks": checks,
    }

    if not all_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return result
