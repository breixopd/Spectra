"""API layer for the Spectra Security Assessment Platform.

Contains:
- routers: FastAPI route handlers for all endpoints
- schemas: Pydantic models for request/response validation
- dependencies: FastAPI dependency injection functions

Endpoints:
- /api/auth - Authentication (login, setup)
- /api/health - Health checks
- /api/targets - Target CRUD operations
- /api/findings - Finding CRUD operations
- /api/exploits - Exploit attempt history
- /api/missions - Mission management
- /api/tools - Tool registry management
- UI routes - Web interface pages
"""

# Re-export from routers subpackage
from app.api.routers import (
    __all__,
    auth_router,
    exploits_router,
    findings_router,
    health_router,
    missions_router,
    targets_router,
    tools_router,
    ui_router,
)
