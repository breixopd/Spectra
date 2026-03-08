"""Role-Based Access Control (RBAC) for Spectra.

Defines permissions per role and provides a FastAPI dependency
to enforce access control on endpoints.
"""

from enum import Enum

from fastapi import Depends, HTTPException

from app.models.user import User


class Permission(str, Enum):
    """Granular permissions used across the platform."""

    VIEW_MISSIONS = "view_missions"
    CREATE_MISSIONS = "create_missions"
    MANAGE_MISSIONS = "manage_missions"
    VIEW_FINDINGS = "view_findings"
    MANAGE_FINDINGS = "manage_findings"
    VIEW_TARGETS = "view_targets"
    MANAGE_TARGETS = "manage_targets"
    USE_TOOLS = "use_tools"
    VIEW_REPORTS = "view_reports"
    MANAGE_SETTINGS = "manage_settings"
    MANAGE_USERS = "manage_users"
    VIEW_AUDIT_LOG = "view_audit_log"
    SHELL_ACCESS = "shell_access"


ROLE_PERMISSIONS: dict[str, set[Permission]] = {
    "admin": set(Permission),
    "operator": {
        Permission.VIEW_MISSIONS,
        Permission.CREATE_MISSIONS,
        Permission.MANAGE_MISSIONS,
        Permission.VIEW_FINDINGS,
        Permission.MANAGE_FINDINGS,
        Permission.VIEW_TARGETS,
        Permission.MANAGE_TARGETS,
        Permission.USE_TOOLS,
        Permission.VIEW_REPORTS,
        Permission.SHELL_ACCESS,
    },
    "viewer": {
        Permission.VIEW_MISSIONS,
        Permission.VIEW_FINDINGS,
        Permission.VIEW_TARGETS,
        Permission.VIEW_REPORTS,
    },
}


def has_permission(user_role: str, permission: Permission) -> bool:
    """Check if a role has a specific permission."""
    return permission in ROLE_PERMISSIONS.get(user_role, set())


def require_permission(permission: Permission):
    """FastAPI dependency that enforces a permission check.

    Usage::

        @router.get("/settings")
        async def get_settings(
            user: User = require_permission(Permission.MANAGE_SETTINGS),
        ):
            ...
    """
    # Deferred import to avoid circular dependency:
    # rbac -> app.api.dependencies -> app.api -> app.api.routers -> (router) -> rbac
    from app.api.dependencies import get_current_active_user

    async def dependency(
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        if not has_permission(current_user.role, permission):
            raise HTTPException(
                status_code=403, detail="Insufficient permissions"
            )
        return current_user

    return Depends(dependency)
