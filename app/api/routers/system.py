"""
System Status API Router.

Aggregates sub-routers for system health and operations.
"""

from fastapi import APIRouter

from app.api.routers.system_health import (
    ClearResponse,
    ComponentStatus,
    OngoingOperation,
    SystemKeys,
    SystemStatusResponse,
    ToolStats,
    _get_cache,
    _get_tool_cache_stats,
    check_embeddings_loading,
    check_tools_installing,
    get_safety_stats,
    get_system_operations,
    get_system_status,
    get_tool_registry,
    health_router,
)
from app.api.routers.system_operations import (
    ClearMissionsRequest,
    operations_router,
)

router = APIRouter(prefix="/system", tags=["System"])
router.include_router(health_router)
router.include_router(operations_router)

# Backward-compatible re-exports
__all__ = [
    "router",
    "ClearMissionsRequest",
    "ClearResponse",
    "ComponentStatus",
    "OngoingOperation",
    "SystemKeys",
    "SystemStatusResponse",
    "ToolStats",
    "_get_cache",
    "_get_tool_cache_stats",
    "check_embeddings_loading",
    "check_tools_installing",
    "get_safety_stats",
    "get_system_operations",
    "get_system_status",
    "get_tool_registry",
]
