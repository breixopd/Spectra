"""System clear and operations management endpoints."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_superuser
from app.core.database import get_async_session
from app.models.mission import Mission
from app.models.user import User

from .schemas import (
    ClearMissionsRequest,
    ClearResponse,
    SystemKeys,
    _get_cache,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Clear endpoints ---


@router.post("/clear/tools", response_model=ClearResponse)
async def clear_tool_statistics(
    _current_user: User = Depends(get_current_superuser),
) -> ClearResponse:
    """Clear tool statistics and status from cache. Requires superuser."""
    cache = _get_cache()
    if not cache:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cache service not available",
        )

    cleared_count = 0

    try:
        patterns = [
            "spectra:tool:*",
            "spectra:tools:status:*",
            "spectra:tools:install:*",
            "spectra:tool_status:*",
        ]

        for pattern in patterns:
            cleared_count += await cache.delete_pattern(pattern)

        logger.info("Cleared %d tool statistic keys from cache", cleared_count)

        return ClearResponse(
            success=True,
            message=f"Cleared {cleared_count} tool statistic entries",
            cleared_count=cleared_count,
        )

    except (ConnectionRefusedError, TimeoutError, OSError) as e:
        logger.error("Service unavailable while clearing tool statistics: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cache service is unavailable",
        )
    except (RuntimeError, ValueError) as e:
        logger.error("Failed to clear tool statistics: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear tool statistics due to an internal error",
        )


@router.post("/clear/missions", response_model=ClearResponse)
async def clear_missions(
    request: ClearMissionsRequest,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_superuser),
) -> ClearResponse:
    """Clear all missions from the database. Requires superuser."""
    if not request.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation required. Set 'confirm' to true to proceed.",
        )

    try:
        if request.status_filter:
            stmt = delete(Mission).where(Mission.status == request.status_filter)
            filter_msg = f" with status '{request.status_filter}'"
        else:
            stmt = delete(Mission)
            filter_msg = ""

        result = await db.execute(stmt)
        await db.commit()

        deleted_count: int = result.rowcount or 0  # type: ignore[assignment]

        cache_cleared = 0
        cache = _get_cache()
        if cache:
            cache_cleared = await cache.delete_pattern("cache:mission:*")

        logger.info(
            "Cleared %d missions%s (and %d cache entries)",
            deleted_count,
            filter_msg,
            cache_cleared,
        )

        return ClearResponse(
            success=True,
            message=f"Cleared {deleted_count} mission(s){filter_msg}",
            cleared_count=deleted_count,
        )

    except (ConnectionRefusedError, TimeoutError, OSError) as e:
        await db.rollback()
        logger.error("Service unavailable while clearing missions: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable",
        )
    except (RuntimeError, ValueError) as e:
        await db.rollback()
        logger.error("Failed to clear missions: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear missions due to an internal error",
        )


@router.post("/clear/cache", response_model=ClearResponse)
async def clear_cache(
    pattern: str = Query(
        default="cache:*",
        description="Cache key pattern to clear (default: cache:*)",
    ),
    _current_user: User = Depends(get_current_superuser),
) -> ClearResponse:
    """Clear cache entries matching a pattern. Requires superuser."""
    allowed_prefixes = ["cache:", "spectra:cache:"]
    if not any(pattern.startswith(prefix) for prefix in allowed_prefixes):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid cache pattern. Must start with 'cache:' or 'spectra:cache:'",
        )

    cache = _get_cache()
    if not cache:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cache service not available",
        )

    try:
        cleared_count = await cache.delete_pattern(pattern)

        logger.info(
            "Cleared %d cache keys matching pattern '%s'", cleared_count, pattern
        )

        return ClearResponse(
            success=True,
            message=f"Cleared {cleared_count} cache entries matching '{pattern}'",
            cleared_count=cleared_count,
        )

    except (ConnectionRefusedError, TimeoutError, OSError) as e:
        logger.error("Service unavailable while clearing cache: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cache service is unavailable",
        )
    except (RuntimeError, ValueError) as e:
        logger.error("Failed to clear cache: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear cache due to an internal error",
        )


# --- Operation Management ---


@router.post("/operations/add")
async def add_operation(
    operation_id: str = Query(..., description="Unique operation identifier"),
    operation_type: str = Query(
        ..., description="Operation type (e.g., installing_tools)"
    ),
    description: str = Query(..., description="Human-readable description"),
    _current_user: User = Depends(get_current_superuser),
) -> dict[str, Any]:
    """Register a new ongoing operation."""
    operation = {
        "id": operation_id,
        "type": operation_type,
        "description": description,
        "started_at": datetime.now(UTC).isoformat(),
        "progress": 0,
    }

    cache = _get_cache()
    if cache:
        await cache.set(
            f"{SystemKeys.OPERATIONS_PREFIX}{operation_id}",
            operation,
            ttl=3600,
        )

    return {"success": True, "operation": operation}


@router.post("/operations/remove")
async def remove_operation(
    operation_id: str = Query(..., description="Operation identifier to remove"),
    _current_user: User = Depends(get_current_superuser),
) -> dict[str, Any]:
    """Remove a completed operation from the tracking list."""
    try:
        cache = _get_cache()
        removed = False
        if cache:
            removed = await cache.delete(
                f"{SystemKeys.OPERATIONS_PREFIX}{operation_id}"
            )

        return {
            "success": removed,
            "message": "Operation removed" if removed else "Operation not found",
        }

    except (ConnectionRefusedError, TimeoutError, OSError) as e:
        logger.error("Service unavailable while removing operation: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cache service is unavailable",
        )
    except (RuntimeError, ValueError) as e:
        logger.error("Failed to remove operation: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to remove operation due to an internal error",
        )


@router.post("/operations/update-progress")
async def update_operation_progress(
    operation_id: str = Query(..., description="Operation identifier"),
    progress: float = Query(
        ..., ge=0, le=100, description="Progress percentage (0-100)"
    ),
    details: str | None = Query(default=None, description="Optional JSON details"),
    _current_user: User = Depends(get_current_superuser),
) -> dict[str, Any]:
    """Update progress for an ongoing operation."""
    try:
        cache = _get_cache()
        if not cache:
            return {"success": False, "message": "Cache not available"}

        key = f"{SystemKeys.OPERATIONS_PREFIX}{operation_id}"
        op = await cache.get(key)
        if not op or not isinstance(op, dict):
            return {"success": False, "message": "Operation not found"}

        op["progress"] = progress
        if details:
            try:
                op["details"] = json.loads(details)
            except json.JSONDecodeError:
                op["details"] = {"message": details}

        await cache.set(key, op, ttl=3600)

        return {"success": True, "message": "Progress updated"}

    except (ConnectionRefusedError, TimeoutError, OSError) as e:
        logger.error("Service unavailable while updating progress: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cache service is unavailable",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except RuntimeError as e:
        logger.error("Failed to update operation progress: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update operation progress due to an internal error",
        )
