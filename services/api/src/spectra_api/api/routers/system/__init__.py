"""
System Status API Router.

Provides endpoints for:
- Overall system status and health
- Clearing tool statistics
- Clearing missions
- Clearing cache
- Data source management
- Service health and topology
- Operations tracking
"""

from fastapi import APIRouter

from .data_sources import router as data_sources_router
from .health import router as health_router
from .operations import router as operations_router

router = APIRouter(prefix="/system", tags=["System"])
router.include_router(health_router)
router.include_router(data_sources_router)
router.include_router(operations_router)
