"""
Health check router.

Provides /api/health for liveness and readiness probes.
Unauthenticated for load balancer/orchestrator use.
"""

import logging

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.version import __version__

logger = logging.getLogger("spectra.health")

router = APIRouter()


@router.get("/health")
async def health_check(
    response: Response,
    db: AsyncSession = Depends(get_async_session),
    verbose: bool = Query(False, description="Include detailed component status"),
):
    """
    Comprehensive health check endpoint.

    Returns 200 if core services (database) are healthy.
    Returns 503 if any critical service is down.

    Use ?verbose=true for detailed component status including RAG, LLM, cache.
    """
    health_status = {
        "status": "healthy",
        "service": "spectra",
        "version": __version__,
        "components": {
            "database": "unknown",
        },
    }
    is_healthy = True

    # Check Database (critical)
    try:
        await db.execute(text("SELECT 1"))
        health_status["components"]["database"] = "healthy"
    except Exception as e:
        health_status["components"]["database"] = f"unhealthy: {type(e).__name__}"
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
            provider = getattr(router_instance, 'provider', 'unknown')
            health_status["components"]["llm"] = f"configured: {provider}"
        except Exception as e:
            health_status["components"]["llm"] = f"unavailable: {type(e).__name__}"

        # Check cache
        try:
            from app.core.cache import get_cache
            cache = get_cache()
            if cache:
                health_status["components"]["cache"] = "healthy"
            else:
                health_status["components"]["cache"] = "unavailable"
        except Exception as e:
            health_status["components"]["cache"] = f"error: {type(e).__name__}"

        # Check tool container connectivity
        try:
            import docker
            from app.core.config import settings
            client = docker.from_env()
            container = client.containers.get(settings.TOOL_CONTAINER_NAME)
            container_status = container.status
            health_status["components"]["tools_container"] = "running" if container_status == "running" else f"status: {container_status}"
        except ImportError:
            health_status["components"]["tools_container"] = "unknown: docker SDK not available"
        except Exception:
            health_status["components"]["tools_container"] = "unreachable"

    if not is_healthy:
        health_status["status"] = "degraded"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return health_status


@router.get("/health/ready")
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
        pass

    # LLM
    try:
        from app.services.ai.router import get_smart_router
        router_instance = get_smart_router()
        checks["llm"] = router_instance is not None
    except Exception:
        pass

    # Embeddings
    try:
        from app.services.ai.rag import RAGService
        rag = RAGService()
        checks["embeddings"] = rag.is_functional
    except Exception:
        pass

    all_ready = all(checks.values())
    result = {
        "ready": all_ready,
        "checks": checks,
    }

    if not all_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return result
