"""
System health check endpoints.

Provides health status, safety stats, tool stats, and overall system status.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_active_user
from app.core.cache import CacheService, get_cache
from app.core.database import get_async_session
from app.models.user import User
from app.services.tools.models import ToolStatus
from app.services.tools.registry import ToolRegistry, get_registry

logger = logging.getLogger("spectra.api.system.health")


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

    status: str = Field(description="Overall system status: ready, initializing, degraded, error")
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
    """Retrieve current ongoing operations from cache."""
    operations: list[OngoingOperation] = []

    if not cache:
        return operations

    try:
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


# --- Router ---

health_router = APIRouter(tags=["System"])


@health_router.get("/safety-stats")
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
            etype = getattr(event, "type", "") or (event.get("type", "") if isinstance(event, dict) else "")
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


@health_router.get("/status", response_model=SystemStatusResponse)
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
    """
    timestamp = datetime.now(UTC).isoformat()
    cache = _get_cache()

    db_status = ComponentStatus(status="unknown")
    cache_status = ComponentStatus(
        status="healthy" if cache else "unavailable",
        message="PostgreSQL-backed cache" if cache else "Cache not initialized",
    )

    try:
        from app.services.storage import get_storage_service

        storage = get_storage_service()
        storage_health = await storage.health_check()
    except Exception as e:
        storage_health = {"status": "unavailable", "error": str(e)}

    overall_status = "ready"
    status_messages: list[str] = []

    try:
        await db.execute(text("SELECT 1"))
        db_status = ComponentStatus(status="healthy", message="Connected")
    except Exception as e:
        logger.error("Database connection check failed: %s", e)
        db_status = ComponentStatus(status="error", message="Connection failed")
        overall_status = "degraded"
        status_messages.append("Database connection issue")

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

    tools_installing = await check_tools_installing(cache)
    embeddings_loading = await check_embeddings_loading(cache)
    operations = await get_system_operations(cache)

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
        setup_message = setup_message or f"Installing {tool_stats.installing} tool(s)..."

    if overall_status == "ready" and setup_complete:
        message = "System is ready"
    elif overall_status == "initializing":
        message = setup_message or "System is initializing..."
    elif overall_status == "degraded":
        message = "System is running with issues: " + ", ".join(status_messages)
    else:
        message = ", ".join(status_messages) if status_messages else "Unknown status"

    resp = SystemStatusResponse(
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
    resp_dict = resp.model_dump()
    resp_dict["storage_health"] = storage_health
    return resp_dict
