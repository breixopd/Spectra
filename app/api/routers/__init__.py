"""API route handlers."""

from .auth import router as auth_router
from .exploits import router as exploits_router
from .findings import router as findings_router
from .health import router as health_router
from .missions import router as missions_router
from .observability import router as observability_router
from .system import router as system_router
from .targets import router as targets_router
from .tools import router as tools_router
from .ui import router as ui_router

__all__ = [
    "health_router",
    "ui_router",
    "auth_router",
    "tools_router",
    "missions_router",
    "targets_router",
    "findings_router",
    "exploits_router",
    "observability_router",
    "system_router",
]
