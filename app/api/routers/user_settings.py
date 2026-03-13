"""User-facing settings API — preferences and BYOK configuration."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import check_feature_allowed, get_current_active_user
from app.api.schemas.user_settings import UserSettingsResponse, UserSettingsUpdate
from app.core.database import get_async_session
from app.core.security import encrypt_byok_key
from app.models.audit_log import AuditEventType
from app.models.user import User
from app.models.user_preferences import UserPreferences
from app.services.system.audit import log_event as audit_log_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/user/settings", tags=["User Settings"])

BYOK_FIELDS = frozenset({
    "llm_api_key", "llm_api_base_url", "llm_model",
    "embedding_api_key", "embedding_api_base_url", "embedding_model",
})

ALLOWED_SETTINGS_FIELDS = frozenset({
    "llm_api_key", "llm_api_base_url", "llm_model",
    "embedding_api_key", "embedding_api_base_url", "embedding_model",
    "email_notifications", "notify_on_mission_complete", "notify_on_critical_finding",
    "webhook_url", "default_scan_mode", "default_report_format", "timezone",
})


def _prefs_to_response(prefs: UserPreferences | None) -> UserSettingsResponse:
    """Convert a DB row (or None) to a masked response."""
    if prefs is None:
        return UserSettingsResponse()
    return UserSettingsResponse(
        llm_api_key_configured=bool(prefs.llm_api_key),
        llm_api_base_url=prefs.llm_api_base_url,
        llm_model=prefs.llm_model,
        embedding_api_key_configured=bool(prefs.embedding_api_key),
        embedding_api_base_url=prefs.embedding_api_base_url,
        embedding_model=prefs.embedding_model,
        email_notifications=prefs.email_notifications,
        webhook_url=prefs.webhook_url,
        notify_on_mission_complete=prefs.notify_on_mission_complete,
        notify_on_critical_finding=prefs.notify_on_critical_finding,
        default_scan_mode=prefs.default_scan_mode,
        default_report_format=prefs.default_report_format,
        timezone=prefs.timezone,
    )


async def _get_prefs(user_id: str, session: AsyncSession) -> UserPreferences | None:
    result = await session.execute(
        select(UserPreferences).where(UserPreferences.user_id == user_id)
    )
    return result.scalar_one_or_none()


@router.get("", response_model=UserSettingsResponse)
async def get_user_settings(
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Return the current user's preferences (API keys masked)."""
    prefs = await _get_prefs(str(user.id), session)
    return _prefs_to_response(prefs)


@router.put("", response_model=UserSettingsResponse)
async def update_user_settings(
    body: UserSettingsUpdate,
    request: Request,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Create or update the current user's preferences.

    BYOK fields require the ``byok`` feature on the user's plan.
    """
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="No fields provided")

    # Enforce BYOK plan gate
    byok_data = {k: v for k, v in updates.items() if k in BYOK_FIELDS and v is not None}
    if byok_data:
        await check_feature_allowed(user, session, "byok")

    prefs = await _get_prefs(str(user.id), session)
    if prefs is None:
        prefs = UserPreferences(user_id=str(user.id))
        session.add(prefs)

    # Encrypt BYOK API keys before storing
    if "llm_api_key" in updates and updates["llm_api_key"]:
        updates["llm_api_key"] = encrypt_byok_key(updates["llm_api_key"])
    if "embedding_api_key" in updates and updates["embedding_api_key"]:
        updates["embedding_api_key"] = encrypt_byok_key(updates["embedding_api_key"])

    for key, value in updates.items():
        if key in ALLOWED_SETTINGS_FIELDS:
            setattr(prefs, key, value)

    await session.commit()
    await session.refresh(prefs)

    try:
        await audit_log_event(
            session, AuditEventType.SETTINGS_CHANGED,
            user_id=str(user.id),
            details={"action": "settings_updated", "fields": list(updates.keys())},
            request=request,
        )
    except Exception:
        pass  # Audit failure shouldn't block the operation

    return _prefs_to_response(prefs)


@router.delete("/byok", status_code=200)
async def clear_byok(
    request: Request,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Clear all BYOK fields from the user's preferences."""
    prefs = await _get_prefs(str(user.id), session)
    if prefs is None:
        return {"detail": "No BYOK configuration to clear"}

    for field in BYOK_FIELDS:
        setattr(prefs, field, None)

    await session.commit()

    try:
        await audit_log_event(
            session, AuditEventType.SETTINGS_CHANGED,
            user_id=str(user.id),
            details={"action": "byok_cleared"},
            request=request,
        )
    except Exception:
        pass

    return {"detail": "BYOK configuration cleared"}
