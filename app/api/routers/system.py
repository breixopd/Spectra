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

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_current_active_user,
)
from app.core.database import get_async_session
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


async def get_system_operations(db: AsyncSession) -> list[OngoingOperation]:
    """
    Retrieve current ongoing operations from DB.
    """
    operations = []

    try:
        from sqlalchemy import select
        from app.models.infrastructure import SystemStatus

        # Check for operations list
        query = select(SystemStatus.value).where(SystemStatus.key.like("spectra:system:operations:%"))
        result = await db.execute(query)
        ops_data = result.scalars().all()

        for op in ops_data:
            if isinstance(op, str):
                try:
                    op = json.loads(op)
                except:
                    continue
            operations.append(
                OngoingOperation(
                    id=op.get("id", "unknown"),
                    type=op.get("type", "unknown"),
                    description=op.get("description", ""),
                    started_at=op.get("started_at"),
                    progress=op.get("progress"),
                    details=op.get("details"),
                )
            )

    except Exception as e:
        logger.warning("Failed to retrieve operations from DB: %s", e)

    return operations


async def check_tools_installing(db: AsyncSession) -> bool:
    """Check if tools are currently being installed."""
    try:
        from sqlalchemy import select
        from app.models.infrastructure import SystemStatus
        query = select(SystemStatus.value).where(SystemStatus.key == "spectra:system:operations:tool_install")
        result = await db.execute(query)
        return result.scalar_one_or_none() is not None
    except Exception:
        return False


async def check_embeddings_loading(db: AsyncSession) -> bool:
    """Check if embeddings are currently loading."""
    try:
        from sqlalchemy import select
        from app.models.infrastructure import SystemStatus
        query = select(SystemStatus.value).where(SystemStatus.key == "spectra:system:operations:embeddings")
        result = await db.execute(query)
        return result.scalar_one_or_none() is not None
    except Exception:
        return False


# --- API Endpoints ---


@router.get("/status", response_model=SystemStatusResponse)
async def get_system_status(
    db: AsyncSession = Depends(get_async_session),
    registry: ToolRegistry = Depends(get_tool_registry),
    _current_user: User = Depends(get_current_active_user),
) -> SystemStatusResponse:
    """
    Get comprehensive system status report.
    """
    timestamp = datetime.utcnow().isoformat() + "Z"

    # Initialize component statuses
    db_status = ComponentStatus(status="unknown")

    overall_status = "ready"
    status_messages = []

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
    tools_installing = await check_tools_installing(db)
    embeddings_loading = await check_embeddings_loading(db)
    operations = await get_system_operations(db)

    # Determine setup status
    setup_complete = True
    setup_message = None

    if not settings.LLM_API_KEY and settings.AI_PROVIDER != "mock":
        setup_complete = False
        setup_message = "AI Provider configuration missing"
        overall_status = "setup_required"

    message = (
        ", ".join(status_messages) if status_messages else "All systems operational"
    )
    if overall_status == "setup_required":
        message = setup_message or "System setup required"

    return SystemStatusResponse(
        status=overall_status,
        message=message,
        timestamp=timestamp,
        database=db_status,
        tools_installing=tools_installing,
        embeddings_loading=embeddings_loading,
        tool_stats=tool_stats,
        operations=operations,
        setup_complete=setup_complete,
        setup_message=setup_message,
    )
