"""Admin settings endpoint for runtime configuration."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import AdminSettingsUpdate
from app.core.database import get_async_session
from app.core.rbac import Permission, require_permission
from app.models.audit_log import AuditEventType
from app.models.user import User
from app.services.system.audit import log_event as audit_log_event
from app.services.system.settings_service import apply_settings_update, get_current_settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/admin/settings")
async def get_admin_settings(
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
) -> dict:
    """Return current runtime system settings."""
    return get_current_settings()


@router.put("/api/admin/settings")
async def update_admin_settings(
    request: Request,
    payload: AdminSettingsUpdate,
    session: AsyncSession = Depends(get_async_session),
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
) -> dict:
    """Update runtime system settings."""
    updated = sorted(payload.model_dump(exclude_unset=True, by_alias=True).keys())
    result = await apply_settings_update(payload.to_settings_update(), session)

    if updated:
        await audit_log_event(
            session,
            AuditEventType.SETTINGS_CHANGED,
            user_id=str(_user.id),
            details={"changed_keys": updated},
            request=request,
        )

    return {**result, "updated": updated}
