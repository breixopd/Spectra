"""System health and status endpoints."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_active_user, get_current_superuser
from app.core.database import get_async_session
from app.models.user import User
from app.services.tools.models import ToolStatus
from app.services.tools.registry import ToolRegistry

from .schemas import (
    ComponentStatus,
    SystemStatusResponse,
    ToolStats,
    _get_cache,
    _get_tool_cache_stats,
    check_embeddings_loading,
    check_tools_installing,
    get_system_operations,
    get_tool_registry,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/safety-stats")
async def get_safety_stats(
    _current_user: User = Depends(get_current_active_user),
) -> dict:
    """Get safety supervisor statistics from EventBus history."""
    try:
        from app.core.events import events as event_bus

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
    except (OSError, RuntimeError, ValueError):
        return {"allowed": 0, "blocked": 0, "flagged": 0}


@router.get("/status", response_model=SystemStatusResponse)
async def get_system_status(
    db: AsyncSession = Depends(get_async_session),
    registry: ToolRegistry = Depends(get_tool_registry),
    _current_user: User = Depends(get_current_active_user),
) -> SystemStatusResponse:
    """Get comprehensive system status."""
    timestamp = datetime.now(UTC).isoformat()
    cache = _get_cache()

    db_status = ComponentStatus(status="unknown")
    cache_status = ComponentStatus(
        status="healthy" if cache else "unavailable",
        message="PostgreSQL-backed cache" if cache else "Cache not initialized",
    )

    # Storage health
    try:
        from app.services.storage import get_storage_service
        storage = get_storage_service()
        storage_health = await storage.health_check()
    except (OSError, RuntimeError, ValueError) as e:
        storage_health = {"status": "unavailable", "error": str(e)}

    overall_status = "ready"
    status_messages: list[str] = []

    # Check database
    try:
        await db.execute(text("SELECT 1"))
        db_status = ComponentStatus(status="healthy", message="Connected")
    except (OSError, RuntimeError) as e:
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
    except (OSError, RuntimeError, ValueError) as e:
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
    except (OSError, RuntimeError, ImportError):
        rag_status = "unavailable"

    if tool_stats.installing > 0:
        setup_complete = False
        setup_message = (
            setup_message or f"Installing {tool_stats.installing} tool(s)..."
        )

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
        storage_health=storage_health,
    )


@router.get("/services/health")
async def service_health(
    _current_user: User = Depends(get_current_superuser),
) -> dict:
    """Health check all registered services."""
    from app.services.gateway.service_registry import get_service_registry

    registry = get_service_registry()
    return await registry.health_check_all()


@router.get("/services/topology")
async def service_topology(
    _current_user: User = Depends(get_current_superuser),
) -> dict:
    """Return current service topology (local vs remote)."""
    from app.services.gateway.service_registry import get_service_registry

    registry = get_service_registry()
    return registry.get_service_topology()


@router.get("/audit-log")
async def get_audit_log(
    skip: int = 0,
    limit: int = 50,
    event_type: str | None = None,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_superuser),
):
    """Get audit log entries. Superuser only."""
    from app.repositories.audit_log import AuditLogRepository

    repo = AuditLogRepository(db)
    entries = await repo.list_events(skip=skip, limit=limit, event_type=event_type)
    return [e.to_dict() for e in entries]
