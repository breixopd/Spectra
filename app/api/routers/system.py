"""
System Status API Router.

Provides endpoints for:
- Overall system status and health
- Clearing tool statistics
- Clearing missions
- Clearing cache
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_current_active_user,
    get_current_superuser,
)
from app.core.cache import CacheService, get_cache
from app.core.database import get_async_session
from app.models.mission import Mission
from app.models.user import User
from app.services.tools.models import ToolStatus
from app.services.tools.registry import ToolRegistry, get_registry

logger = logging.getLogger("spectra.api.system")

router = APIRouter(prefix="/system", tags=["System"])


# --- Cache Key Constants ---
class SystemKeys:
    """Cache key constants for system state."""

    STATUS = "spectra:system:status"
    OPERATIONS_PREFIX = "spectra:system:operations:"
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
    cache: ComponentStatus

    # Tool status
    tools_installing: bool = False
    embeddings_loading: bool = False
    tool_stats: ToolStats

    # Ongoing operations
    operations: list[OngoingOperation] = []

    # Setup progress info
    setup_complete: bool = True
    setup_message: str | None = None

    # RAG status
    rag_status: str = "unknown"

    # Tool cache stats
    tool_cache_stats: dict[str, int] | None = None


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


def _get_cache() -> CacheService | None:
    """Get the cache service instance."""
    return get_cache()


def _get_tool_cache_stats() -> dict[str, int]:
    """Get tool result cache statistics."""
    try:
        from app.core.optimizations import tool_cache
        return tool_cache.stats
    except Exception:
        return {"size": 0, "hits": 0, "misses": 0, "hit_rate_pct": 0}


async def get_system_operations(cache: CacheService | None) -> list[OngoingOperation]:
    """
    Retrieve current ongoing operations from cache.

    Args:
        cache: CacheService instance.

    Returns:
        List of ongoing operations.
    """
    operations: list[OngoingOperation] = []

    if not cache:
        return operations

    try:
        # Operations are stored as individual cache keys
        ops_data = await cache.get_by_pattern(f"{SystemKeys.OPERATIONS_PREFIX}*")
        for op in ops_data:
            try:
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
            except (TypeError, KeyError):
                continue

        # Check for tool installation progress
        install_progress = await cache.get(SystemKeys.INSTALL_PROGRESS)
        if install_progress:
            if isinstance(install_progress, dict) and install_progress.get("active"):
                operations.append(
                    OngoingOperation(
                        id="tool_installation",
                        type="installing_tools",
                        description=f"Installing tools: {install_progress.get('current', 'unknown')}",
                        started_at=install_progress.get("started_at"),
                        progress=install_progress.get("progress", 0),
                        details={
                            "current_tool": install_progress.get("current"),
                            "total": install_progress.get("total", 0),
                            "completed": install_progress.get("completed", 0),
                        },
                    )
                )

        # Check for embeddings loading
        embeddings_status = await cache.get(SystemKeys.EMBEDDINGS_STATUS)
        if embeddings_status:
            if isinstance(embeddings_status, dict) and embeddings_status.get("loading"):
                operations.append(
                    OngoingOperation(
                        id="embeddings_loading",
                        type="loading_embeddings",
                        description="Loading knowledge base embeddings",
                        started_at=embeddings_status.get("started_at"),
                        progress=embeddings_status.get("progress"),
                        details=embeddings_status.get("details"),
                    )
                )

    except Exception as e:
        logger.warning("Failed to retrieve operations from cache: %s", e)

    return operations


async def check_tools_installing(cache: CacheService | None) -> bool:
    """Check if tools are currently being installed."""
    if not cache:
        return False
    try:
        progress = await cache.get(SystemKeys.INSTALL_PROGRESS)
        if isinstance(progress, dict):
            return progress.get("active", False)
    except Exception as e:
        logger.debug("System status check failed: %s", e)
    return False


async def check_embeddings_loading(cache: CacheService | None) -> bool:
    """Check if embeddings are currently loading."""
    if not cache:
        return False
    try:
        emb_status = await cache.get(SystemKeys.EMBEDDINGS_STATUS)
        if isinstance(emb_status, dict):
            return emb_status.get("loading", False)
    except Exception as e:
        logger.debug("System status check failed: %s", e)
    return False


# --- API Endpoints ---


@router.get("/safety-stats")
async def get_safety_stats(
    _current_user: User = Depends(get_current_active_user),
) -> dict:
    """Get safety supervisor statistics from EventBus history."""
    try:
        from app.core.events import event_bus

        allowed = 0
        blocked = 0
        flagged = 0
        for event in getattr(event_bus, "history", []):
            etype = getattr(event, "type", "") or (
                event.get("type", "") if isinstance(event, dict) else ""
            )
            if etype == "safety_check":
                data = (
                    getattr(event, "data", {})
                    if hasattr(event, "data")
                    else (event.get("data", {}) if isinstance(event, dict) else {})
                )
                if data.get("allowed"):
                    allowed += 1
                else:
                    blocked += 1
            elif etype == "tool_result":
                allowed += 1
            elif etype == "safety_flag":
                flagged += 1

        return {"allowed": allowed, "blocked": blocked, "flagged": flagged}
    except Exception:
        return {"allowed": 0, "blocked": 0, "flagged": 0}


@router.get("/status", response_model=SystemStatusResponse)
async def get_system_status(
    db: AsyncSession = Depends(get_async_session),
    registry: ToolRegistry = Depends(get_tool_registry),
    _current_user: User = Depends(get_current_active_user),
) -> SystemStatusResponse:
    """
    Get comprehensive system status.

    Returns overall system health including:
    - Database connectivity
    - Cache health
    - Tool installation status
    - Embeddings loading status
    - Number of tools by status
    - Current ongoing operations

    Use this endpoint to show appropriate UI messages during setup/initialization.
    """
    timestamp = datetime.now(UTC).isoformat()
    cache = _get_cache()

    # Initialize component statuses
    db_status = ComponentStatus(status="unknown")
    cache_status = ComponentStatus(
        status="healthy" if cache else "unavailable",
        message="PostgreSQL-backed cache" if cache else "Cache not initialized",
    )

    overall_status = "ready"
    status_messages: list[str] = []

    # Check database
    try:
        await db.execute(text("SELECT 1"))
        db_status = ComponentStatus(status="healthy", message="Connected")
    except Exception as e:
        logger.error("Database connection check failed: %s", e)
        db_status = ComponentStatus(status="error", message="Connection failed")
        overall_status = "degraded"
        status_messages.append("Database connection issue")

    # Get tool statistics
    tool_stats = ToolStats()
    try:
        await registry.sync_status_from_cache()
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

    # Check ongoing operations via cache
    tools_installing = await check_tools_installing(cache)
    embeddings_loading = await check_embeddings_loading(cache)
    operations = await get_system_operations(cache)

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

    # Check RAG/embedding service health
    rag_status = "unknown"
    try:
        from app.services.ai.rag import RAGService
        rag = RAGService()
        if rag.is_functional:
            rag_status = "healthy"
        else:
            rag_status = "fallback"
            if overall_status == "ready":
                status_messages.append("RAG using fallback embeddings")
    except Exception:
        rag_status = "unavailable"

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
        cache=cache_status,
        tools_installing=tools_installing,
        embeddings_loading=embeddings_loading,
        tool_stats=tool_stats,
        operations=operations,
        setup_complete=setup_complete,
        setup_message=setup_message,
        rag_status=rag_status,
        tool_cache_stats=_get_tool_cache_stats(),
    )


@router.post("/clear/tools", response_model=ClearResponse)
async def clear_tool_statistics(
    _current_user: User = Depends(get_current_superuser),
) -> ClearResponse:
    """
    Clear tool statistics and status from cache.

    This clears cached tool status information, forcing a refresh on next query.
    Requires superuser privileges.
    """
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

    except Exception as e:
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

        # Clear mission cache entries
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

    except Exception as e:
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
    """
    Clear cache entries.

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

    except Exception as e:
        logger.error("Failed to clear cache: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear cache due to an internal error",
        )


# --- System Operation Management ---


@router.post("/operations/add")
async def add_operation(
    operation_id: str = Query(..., description="Unique operation identifier"),
    operation_type: str = Query(
        ..., description="Operation type (e.g., installing_tools)"
    ),
    description: str = Query(..., description="Human-readable description"),
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
    """
    Remove a completed operation from the tracking list.
    """
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

    except Exception as e:
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
    """
    Update progress for an ongoing operation.
    """
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

    except Exception as e:
        logger.error("Failed to update operation progress: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update operation progress due to an internal error",
        )


# --- Data Sources ---


@router.get("/data-sources")
async def get_data_source_status(
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Get status of all downloadable data sources (exploit DB, CVE KB, etc.)."""
    from app.services.ai.exploit_db import get_exploit_db

    db = get_exploit_db()
    return db.data_status()


@router.post("/data-sources/download")
async def download_data_sources(
    _current_user: User = Depends(get_current_superuser),
) -> dict[str, Any]:
    """Download/update all exploit intelligence data sources.

    Downloads MSF modules, CISA KEV, and writes the CVE knowledge base.
    """
    import json as _json
    from pathlib import Path as _Path

    from app.core.constants import EXPLOIT_DB_CACHE_DIR
    from app.services.ai.exploit_db import get_exploit_db

    db = get_exploit_db()

    # Write CVE knowledge base from the update script's data
    try:
        from scripts.update_exploit_db import _CVE_KNOWLEDGE_BASE

        cache_dir = _Path(EXPLOIT_DB_CACHE_DIR)
        cache_dir.mkdir(parents=True, exist_ok=True)
        kb_path = cache_dir / "cve_knowledge_base.json"
        kb_path.write_text(_json.dumps(_CVE_KNOWLEDGE_BASE, indent=2))
        kb_count = len(_CVE_KNOWLEDGE_BASE)
    except Exception as exc:
        logger.warning("Failed to write CVE knowledge base: %s", exc)
        kb_count = 0

    # Reload CVE knowledge base in memory
    from app.services.ai.cve_intel import reload_cve_knowledge_base

    reload_cve_knowledge_base()

    # Download exploit sources
    stats = await db.update()
    stats["cve_kb_entries"] = kb_count

    return {"success": True, "message": "Data sources updated", "stats": stats}


@router.get("/audit-log")
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
