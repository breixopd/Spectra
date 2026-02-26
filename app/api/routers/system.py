"""
System Status API Router.

Provides endpoints for:
- Overall system status and health
- Clearing tool statistics
- Clearing missions
- Clearing Redis cache
"""

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_current_active_user,
    get_current_superuser,
    get_redis,
)
from app.core.database import get_async_session
from app.models.mission import Mission
from app.models.user import User
from app.services.tools.models import ToolStatus
from app.services.tools.registry import ToolRegistry, get_registry

logger = logging.getLogger("spectra.api.system")

router = APIRouter(prefix="/system", tags=["System"])


# --- Redis Key Constants ---
class SystemKeys:
    """Redis key constants for system state."""

    STATUS = "spectra:system:status"
    OPERATIONS = "spectra:system:operations"
    TOOL_STATS = "spectra:tool:*"
    TOOL_STATUS = "spectra:tools:status:*"
    EMBEDDINGS_STATUS = "spectra:embeddings:status"
    INSTALL_PROGRESS = "spectra:tools:install:progress"


# --- Pydantic Schemas ---


class ToolStats(BaseModel):
    """Tool statistics summary."""

    total: int = 0
    ready: int = 0
    installing: int = 0
    pending: int = 0
    failed: int = 0
    disabled: int = 0


class ComponentStatus(BaseModel):
    """Status of a system component."""

    status: str = "unknown"
    message: str | None = None
    details: dict[str, Any] | None = None


class OngoingOperation(BaseModel):
    """Information about an ongoing operation."""

    id: str
    type: str
    description: str
    started_at: str | None = None
    progress: float | None = None
    details: dict[str, Any] | None = None


class SystemStatusResponse(BaseModel):
    """Complete system status response."""

    status: str = Field(
        description="Overall system status: ready, initializing, degraded, error"
    )
    message: str = Field(description="Human-readable status message for UI display")
    timestamp: str = Field(description="ISO timestamp of status check")

    # Component statuses
    database: ComponentStatus
    redis: ComponentStatus

    # Tool status
    tools_installing: bool = False
    embeddings_loading: bool = False
    tool_stats: ToolStats

    # Ongoing operations
    operations: list[OngoingOperation] = []

    # Setup progress info
    setup_complete: bool = True
    setup_message: str | None = None


class ClearResponse(BaseModel):
    """Response for clear operations."""

    success: bool
    message: str
    cleared_count: int | None = None


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


# --- Helper Functions ---


def get_tool_registry() -> ToolRegistry:
    """Dependency to get the tool registry."""
    return get_registry()


async def get_system_operations(redis: Redis) -> list[OngoingOperation]:
    """
    Retrieve current ongoing operations from Redis.

    Args:
        redis: Redis client instance.

    Returns:
        List of ongoing operations.
    """
    operations = []

    try:
        # Check for operations list
        ops_data = await redis.lrange(SystemKeys.OPERATIONS, 0, -1)  # type: ignore[misc]
        for op_json in ops_data:
            try:
                op = json.loads(op_json)
                operations.append(
                    OngoingOperation(
                        id=op.get("id", "unknown"),
                        type=op.get("type", "unknown"),
                        description=op.get("description", "Unknown operation"),
                        started_at=op.get("started_at"),
                        progress=op.get("progress"),
                        details=op.get("details"),
                    )
                )
            except (json.JSONDecodeError, TypeError):
                continue

        # Check for tool installation progress
        install_progress = await redis.get(SystemKeys.INSTALL_PROGRESS)
        if install_progress:
            try:
                progress = json.loads(install_progress)
                if progress.get("active"):
                    operations.append(
                        OngoingOperation(
                            id="tool_installation",
                            type="installing_tools",
                            description=f"Installing tools: {progress.get('current', 'unknown')}",
                            started_at=progress.get("started_at"),
                            progress=progress.get("progress", 0),
                            details={
                                "current_tool": progress.get("current"),
                                "total": progress.get("total", 0),
                                "completed": progress.get("completed", 0),
                            },
                        )
                    )
            except (json.JSONDecodeError, TypeError):
                pass

        # Check for embeddings loading
        embeddings_status = await redis.get(SystemKeys.EMBEDDINGS_STATUS)
        if embeddings_status:
            try:
                emb_data = json.loads(embeddings_status)
                if emb_data.get("loading"):
                    operations.append(
                        OngoingOperation(
                            id="embeddings_loading",
                            type="loading_embeddings",
                            description="Loading knowledge base embeddings",
                            started_at=emb_data.get("started_at"),
                            progress=emb_data.get("progress"),
                            details=emb_data.get("details"),
                        )
                    )
            except (json.JSONDecodeError, TypeError):
                pass

    except Exception as e:
        logger.warning("Failed to retrieve operations from Redis: %s", e)

    return operations


async def check_tools_installing(redis: Redis) -> bool:
    """Check if tools are currently being installed."""
    try:
        progress = await redis.get(SystemKeys.INSTALL_PROGRESS)
        if progress:
            data = json.loads(progress)
            return data.get("active", False)
    except Exception:
        pass
    return False


async def check_embeddings_loading(redis: Redis) -> bool:
    """Check if embeddings are currently loading."""
    try:
        status = await redis.get(SystemKeys.EMBEDDINGS_STATUS)
        if status:
            data = json.loads(status)
            return data.get("loading", False)
    except Exception:
        pass
    return False


# --- API Endpoints ---


@router.get("/status", response_model=SystemStatusResponse)
async def get_system_status(
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_async_session),
    registry: ToolRegistry = Depends(get_tool_registry),
    _current_user: User = Depends(get_current_active_user),
) -> SystemStatusResponse:
    """
    Get comprehensive system status.

    Returns overall system health including:
    - Database and Redis connectivity
    - Tool installation status
    - Embeddings loading status
    - Number of tools by status
    - Current ongoing operations

    Use this endpoint to show appropriate UI messages during setup/initialization.
    """
    timestamp = datetime.utcnow().isoformat() + "Z"

    # Initialize component statuses
    db_status = ComponentStatus(status="unknown")
    redis_status = ComponentStatus(status="unknown")

    overall_status = "ready"
    status_messages = []

    # Check database
    try:
        await db.execute(text("SELECT 1"))
        db_status = ComponentStatus(status="healthy", message="Connected")
    except Exception as e:
        db_status = ComponentStatus(status="error", message=str(e))
        overall_status = "degraded"
        status_messages.append("Database connection issue")

    # Check Redis
    try:
        await redis.ping()
        redis_status = ComponentStatus(status="healthy", message="Connected")
    except Exception as e:
        redis_status = ComponentStatus(status="error", message=str(e))
        overall_status = "degraded"
        status_messages.append("Redis connection issue")

    # Get tool statistics
    tool_stats = ToolStats()
    try:
        # Sync from Redis first
        await registry.sync_status_from_redis()
        tools = registry.list_tools()

        tool_stats.total = len(tools)
        for tool in tools:
            if tool.status == ToolStatus.READY:
                tool_stats.ready += 1
            elif tool.status == ToolStatus.INSTALLING:
                tool_stats.installing += 1
            elif tool.status == ToolStatus.PENDING:
                tool_stats.pending += 1
            elif tool.status == ToolStatus.FAILED:
                tool_stats.failed += 1
            elif tool.status == ToolStatus.DISABLED:
                tool_stats.disabled += 1
    except Exception as e:
        logger.warning("Failed to get tool stats: %s", e)

    # Check ongoing operations
    tools_installing = await check_tools_installing(redis)
    embeddings_loading = await check_embeddings_loading(redis)
    operations = await get_system_operations(redis)

    # Determine setup status
    setup_complete = True
    setup_message = None

    if tools_installing:
        setup_complete = False
        setup_message = "Installing security tools..."
        overall_status = "initializing"
        status_messages.append("Tools installing")

    if embeddings_loading:
        setup_complete = False
        setup_message = setup_message or "Loading knowledge base..."
        if overall_status != "degraded":
            overall_status = "initializing"
        status_messages.append("Embeddings loading")

    if tool_stats.installing > 0:
        setup_complete = False
        setup_message = (
            setup_message or f"Installing {tool_stats.installing} tool(s)..."
        )

    # Generate overall message
    if overall_status == "ready" and setup_complete:
        message = "System is ready"
    elif overall_status == "initializing":
        message = setup_message or "System is initializing..."
    elif overall_status == "degraded":
        message = "System is running with issues: " + ", ".join(status_messages)
    else:
        message = ", ".join(status_messages) if status_messages else "Unknown status"

    return SystemStatusResponse(
        status=overall_status,
        message=message,
        timestamp=timestamp,
        database=db_status,
        redis=redis_status,
        tools_installing=tools_installing,
        embeddings_loading=embeddings_loading,
        tool_stats=tool_stats,
        operations=operations,
        setup_complete=setup_complete,
        setup_message=setup_message,
    )


@router.post("/clear/tools", response_model=ClearResponse)
async def clear_tool_statistics(
    redis: Redis = Depends(get_redis),
    _current_user: User = Depends(get_current_superuser),
) -> ClearResponse:
    """
    Clear tool statistics and status from Redis.

    This clears cached tool status information, forcing a refresh on next query.
    Requires superuser privileges.
    """
    cleared_count = 0

    try:
        # Find and delete all tool-related keys
        patterns = [
            "spectra:tool:*",
            "spectra:tools:status:*",
            "spectra:tools:install:*",
        ]

        for pattern in patterns:
            cursor = 0
            while True:
                cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100)
                if keys:
                    await redis.delete(*keys)
                    cleared_count += len(keys)
                if cursor == 0:
                    break

        logger.info("Cleared %d tool statistic keys from Redis", cleared_count)

        return ClearResponse(
            success=True,
            message=f"Cleared {cleared_count} tool statistic entries",
            cleared_count=cleared_count,
        )

    except Exception as e:
        logger.error("Failed to clear tool statistics: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear tool statistics: {str(e)}",
        )


@router.post("/clear/missions", response_model=ClearResponse)
async def clear_missions(
    request: ClearMissionsRequest,
    db: AsyncSession = Depends(get_async_session),
    redis: Redis = Depends(get_redis),
    _current_user: User = Depends(get_current_superuser),
) -> ClearResponse:
    """
    Clear all missions from the database.

    Requires explicit confirmation (confirm=true) to prevent accidental deletion.
    Optionally filter by status to only clear specific missions.
    Requires superuser privileges.
    """
    if not request.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation required. Set 'confirm' to true to proceed.",
        )

    try:
        # Build delete query
        if request.status_filter:
            stmt = delete(Mission).where(Mission.status == request.status_filter)
            filter_msg = f" with status '{request.status_filter}'"
        else:
            stmt = delete(Mission)
            filter_msg = ""

        # Execute deletion
        result = await db.execute(stmt)
        await db.commit()

        deleted_count: int = result.rowcount or 0  # type: ignore[assignment]

        # Also clear any mission-related cache in Redis
        cursor = 0
        redis_cleared = 0
        while True:
            cursor, keys = await redis.scan(
                cursor=cursor, match="cache:mission:*", count=100
            )
            if keys:
                await redis.delete(*keys)
                redis_cleared += len(keys)
            if cursor == 0:
                break

        logger.info(
            "Cleared %d missions%s (and %d cache entries)",
            deleted_count,
            filter_msg,
            redis_cleared,
        )

        return ClearResponse(
            success=True,
            message=f"Cleared {deleted_count} mission(s){filter_msg}",
            cleared_count=deleted_count,
        )

    except Exception as e:
        await db.rollback()
        logger.error("Failed to clear missions: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear missions: {str(e)}",
        )


@router.post("/clear/cache", response_model=ClearResponse)
async def clear_cache(
    pattern: str = Query(
        default="cache:*",
        description="Redis key pattern to clear (default: cache:*)",
    ),
    redis: Redis = Depends(get_redis),
    _current_user: User = Depends(get_current_superuser),
) -> ClearResponse:
    """
    Clear Redis cache.

    By default clears all cache entries (pattern: cache:*).
    Can specify a custom pattern to clear specific cache types:
    - cache:tool:* - Tool cache
    - cache:mission:* - Mission cache
    - cache:finding:* - Finding cache
    - cache:rag:* - RAG/embedding cache
    - cache:stats:* - Statistics cache

    Requires superuser privileges.
    """
    # Validate pattern to prevent clearing system keys accidentally
    allowed_prefixes = ["cache:", "spectra:cache:"]
    if not any(pattern.startswith(prefix) for prefix in allowed_prefixes):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid cache pattern. Must start with 'cache:' or 'spectra:cache:'",
        )

    try:
        cleared_count = 0
        cursor = 0

        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                await redis.delete(*keys)
                cleared_count += len(keys)
            if cursor == 0:
                break

        logger.info(
            "Cleared %d cache keys matching pattern '%s'", cleared_count, pattern
        )

        return ClearResponse(
            success=True,
            message=f"Cleared {cleared_count} cache entries matching '{pattern}'",
            cleared_count=cleared_count,
        )

    except Exception as e:
        logger.error("Failed to clear cache: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear cache: {str(e)}",
        )


# --- System Operation Management ---


@router.post("/operations/add")
async def add_operation(
    operation_id: str = Query(..., description="Unique operation identifier"),
    operation_type: str = Query(
        ..., description="Operation type (e.g., installing_tools)"
    ),
    description: str = Query(..., description="Human-readable description"),
    redis: Redis = Depends(get_redis),
    _current_user: User = Depends(get_current_superuser),
) -> dict[str, Any]:
    """
    Register a new ongoing operation.

    Used internally to track long-running operations like tool installation
    or embedding loading.
    """
    operation = {
        "id": operation_id,
        "type": operation_type,
        "description": description,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "progress": 0,
    }

    await redis.rpush(SystemKeys.OPERATIONS, json.dumps(operation))  # type: ignore[misc]

    return {"success": True, "operation": operation}


@router.post("/operations/remove")
async def remove_operation(
    operation_id: str = Query(..., description="Operation identifier to remove"),
    redis: Redis = Depends(get_redis),
    _current_user: User = Depends(get_current_superuser),
) -> dict[str, Any]:
    """
    Remove a completed operation from the tracking list.
    """
    try:
        # Get all operations
        ops = await redis.lrange(SystemKeys.OPERATIONS, 0, -1)  # type: ignore[misc]

        # Filter out the one to remove
        remaining = []
        removed = False
        for op_json in ops:
            try:
                op = json.loads(op_json)
                if op.get("id") != operation_id:
                    remaining.append(op_json)
                else:
                    removed = True
            except (json.JSONDecodeError, TypeError):
                continue

        # Replace the list
        if removed:
            await redis.delete(SystemKeys.OPERATIONS)
            if remaining:
                await redis.rpush(SystemKeys.OPERATIONS, *remaining)  # type: ignore[misc]

        return {
            "success": removed,
            "message": "Operation removed" if removed else "Operation not found",
        }

    except Exception as e:
        logger.error("Failed to remove operation: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remove operation: {str(e)}",
        )


@router.post("/operations/update-progress")
async def update_operation_progress(
    operation_id: str = Query(..., description="Operation identifier"),
    progress: float = Query(
        ..., ge=0, le=100, description="Progress percentage (0-100)"
    ),
    details: str | None = Query(default=None, description="Optional JSON details"),
    redis: Redis = Depends(get_redis),
    _current_user: User = Depends(get_current_superuser),
) -> dict[str, Any]:
    """
    Update progress for an ongoing operation.
    """
    try:
        # Get all operations
        ops = await redis.lrange(SystemKeys.OPERATIONS, 0, -1)  # type: ignore[misc]

        # Update the target operation
        updated_ops = []
        found = False
        for op_json in ops:
            try:
                op = json.loads(op_json)
                if op.get("id") == operation_id:
                    op["progress"] = progress
                    if details:
                        try:
                            op["details"] = json.loads(details)
                        except json.JSONDecodeError:
                            op["details"] = {"message": details}
                    found = True
                updated_ops.append(json.dumps(op))
            except (json.JSONDecodeError, TypeError):
                continue

        # Replace the list
        if found:
            await redis.delete(SystemKeys.OPERATIONS)
            if updated_ops:
                await redis.rpush(SystemKeys.OPERATIONS, *updated_ops)  # type: ignore[misc]

        return {
            "success": found,
            "message": "Progress updated" if found else "Operation not found",
        }

    except Exception as e:
        logger.error("Failed to update operation progress: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update operation progress: {str(e)}",
        )
