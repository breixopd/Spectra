"""Admin panel API router.

Provides user management, plan management, audit logs, server provisioning,
and dashboard statistics. All endpoints require the admin role.

Split into submodules for maintainability:
- users: User CRUD + admin page
- plans: Plan CRUD
- servers: Server provisioning + pool management
- audit: Audit logs + dashboard statistics
"""

from fastapi import APIRouter

from .audit import router as audit_router
from .content import router as content_router
from .email import router as email_router
from .plans import router as plans_router
from .servers import router as servers_router
from .settings import router as settings_router
from .tensorzero import router as tensorzero_router
from .users import router as users_router

router = APIRouter()
router.include_router(users_router)
router.include_router(plans_router)
router.include_router(servers_router)
router.include_router(audit_router)
router.include_router(content_router)
router.include_router(email_router)
router.include_router(settings_router)
router.include_router(tensorzero_router)
