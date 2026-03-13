"""System router schemas and helper functions."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.core.cache import CacheService, get_cache
from app.services.tools.registry import ToolRegistry, get_registry

logger = logging.getLogger(__name__)


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
