"""
Health check router.
"""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session

router = APIRouter()


@router.get("/health")
async def health_check(
    response: Response,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Comprehensive health check endpoint.
    Checks connectivity to Database.
    Returns 200 if all healthy, 503 if any critical service is down.
    """
    health_status = {
        "status": "healthy",
        "service": "spectra",
        "components": {
            "database": "unknown",
        },
    }
    is_healthy = True

    # Check Database
    try:
        await db.execute(text("SELECT 1"))
        health_status["components"]["database"] = "healthy"
    except Exception:
        health_status["components"]["database"] = "unhealthy: Connection failed"
        is_healthy = False

    if not is_healthy:
        health_status["status"] = "degraded"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return health_status
