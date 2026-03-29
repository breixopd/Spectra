"""Admin settings endpoint for runtime configuration."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.rbac import Permission, require_permission
from app.models.audit_log import AuditEventType
from app.models.config import SystemConfig
from app.models.user import User
from app.services.system.audit import log_event as audit_log_event
from app.services.system.runtime_settings import GENERAL_RUNTIME_FIELD_MAP

logger = logging.getLogger(__name__)

router = APIRouter()


@router.put("/api/admin/settings")
async def update_admin_settings(
    request: Request,
    payload: dict,
    session: AsyncSession = Depends(get_async_session),
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
) -> dict:
    """Update runtime system settings."""
    updated = []
    for key, value in payload.items():
        if key not in GENERAL_RUNTIME_FIELD_MAP:
            continue
        result = await session.execute(
            select(SystemConfig).where(SystemConfig.key == key)
        )
        config = result.scalar_one_or_none()
        str_value = str(value) if value is not None else ""
        if config:
            config.value = str_value
        else:
            session.add(SystemConfig(key=key, value=str_value))
        updated.append(key)
    await session.commit()

    if updated:
        await audit_log_event(
            session,
            AuditEventType.SETTINGS_CHANGED,
            user_id=str(_user.id),
            details={"changed_keys": updated},
            request=request,
        )

    return {"updated": updated}
