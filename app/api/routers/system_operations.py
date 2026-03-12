"""
System operations endpoints.

Provides endpoints for:
- Clearing tool statistics, missions, cache
- Managing ongoing operations
- Data source management
- Service health and topology
- Audit log
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_current_active_user,
    get_current_superuser,
)
from app.api.routers.system_health import (
    ClearResponse,
    SystemKeys,
    _get_cache,
)
from app.core.database import get_async_session
from app.models.mission import Mission
from app.models.user import User

logger = logging.getLogger("spectra.api.system.operations")


# --- Request Models ---


class ClearMissionsRequest(BaseModel):
    """Request body for clearing missions."""

    confirm: bool = Field(
        default=False,
        description="Must be true to confirm mission deletion",
    )
    status_filter: str | None = Field(
        default=None,
        description="Optional: only clear missions with this status",
    )


# --- Router ---

operations_router = APIRouter(tags=["System"])


@operations_router.post("/clear/tools", response_model=ClearResponse)
async def clear_tool_statistics(
    _current_user: User = Depends(get_current_superuser),
) -> ClearResponse:
    """Clear tool statistics and status from cache."""
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

    except (ConnectionRefusedError, OSError) as e:
        logger.error("Service unavailable while clearing tool statistics: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cache service is unavailable",
        )
    except TimeoutError as e:
        logger.error("Timeout while clearing tool statistics: %s", e)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Operation timed out",
        )
    except Exception as e:
        logger.error("Failed to clear tool statistics: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear tool statistics due to an internal error",
        )


@operations_router.post("/clear/missions", response_model=ClearResponse)
async def clear_missions(
    request: ClearMissionsRequest,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_superuser),
) -> ClearResponse:
    """Clear all missions from the database."""
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

    except (ConnectionRefusedError, OSError) as e:
        await db.rollback()
        logger.error("Service unavailable while clearing missions: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service is unavailable",
        )
    except TimeoutError as e:
        await db.rollback()
        logger.error("Timeout while clearing missions: %s", e)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Operation timed out",
        )
    except Exception as e:
        await db.rollback()
        logger.error("Failed to clear missions: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear missions due to an internal error",
        )


@operations_router.post("/clear/cache", response_model=ClearResponse)
async def clear_cache(
    pattern: str = Query(
        default="cache:*",
        description="Cache key pattern to clear (default: cache:*)",
    ),
    _current_user: User = Depends(get_current_superuser),
) -> ClearResponse:
    """Clear cache entries matching a pattern."""
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

    except (ConnectionRefusedError, OSError) as e:
        logger.error("Service unavailable while clearing cache: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cache service is unavailable",
        )
    except TimeoutError as e:
        logger.error("Timeout while clearing cache: %s", e)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Operation timed out",
        )
    except Exception as e:
        logger.error("Failed to clear cache: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear cache due to an internal error",
        )


# --- System Operation Management ---


@operations_router.post("/operations/add")
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


@operations_router.post("/operations/remove")
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

    except (ConnectionRefusedError, OSError) as e:
        logger.error("Service unavailable while removing operation: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cache service is unavailable",
        )
    except TimeoutError as e:
        logger.error("Timeout while removing operation: %s", e)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Operation timed out",
        )
    except Exception as e:
        logger.error("Failed to remove operation: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to remove operation due to an internal error",
        )


@operations_router.post("/operations/update-progress")
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

    except (ConnectionRefusedError, OSError) as e:
        logger.error("Service unavailable while updating progress: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cache service is unavailable",
        )
    except TimeoutError as e:
        logger.error("Timeout while updating progress: %s", e)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Operation timed out",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error("Failed to update operation progress: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update operation progress due to an internal error",
        )


# --- Data Sources ---


@operations_router.get("/data-sources")
async def get_data_source_status(
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Get status of all data sources (exploit DB, CVE KB, etc.)."""
    from app.services.ai.exploit_db import get_exploit_db

    db = get_exploit_db()
    return db.data_status()


@operations_router.post("/data-sources/refresh")
async def refresh_data_sources(
    _current_user: User = Depends(get_current_superuser),
) -> dict[str, Any]:
    """Trigger a background refresh of all exploit intelligence data sources."""
    import asyncio as _asyncio

    from app.services.ai.exploit_db import get_exploit_db

    db = get_exploit_db()

    async def _do_refresh() -> None:
        try:
            await db.update()
            from app.services.ai.cve_intel import reload_cve_knowledge_base

            reload_cve_knowledge_base()
            logger.info("Background data-source refresh completed")
        except Exception:
            logger.exception("Background data-source refresh failed")

    _asyncio.get_running_loop().create_task(_do_refresh())

    return {
        "success": True,
        "message": "Data source refresh started in background",
    }


@operations_router.get("/audit-log")
async def get_audit_log(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    event_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_superuser),
):
    """Get audit log entries. Superuser only."""
    from app.repositories.audit_log import AuditLogRepository

    repo = AuditLogRepository(db)
    entries = await repo.list_events(skip=skip, limit=limit, event_type=event_type)
    return [e.to_dict() for e in entries]


@operations_router.get("/services/health")
async def service_health(
    _current_user: User = Depends(get_current_superuser),
) -> dict:
    """Health check all registered services."""
    from app.services.gateway.service_registry import get_service_registry

    registry = get_service_registry()
    return await registry.health_check_all()


@operations_router.get("/services/topology")
async def service_topology(
    _current_user: User = Depends(get_current_superuser),
) -> dict:
    """Return current service topology (local vs remote)."""
    from app.services.gateway.service_registry import get_service_registry

    registry = get_service_registry()
    return registry.get_service_topology()
