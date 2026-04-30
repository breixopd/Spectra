"""User-facing settings API — preferences and BYOK configuration."""

import contextlib
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.models.audit_log import AuditEventType
from app.models.user import User
from app.models.user_preferences import UserPreferences
from app.services.system.audit import log_event as audit_log_event
from spectra_api.api.dependencies import check_feature_allowed, get_current_active_user
from spectra_api.api.schemas.user_settings import UserSettingsResponse, UserSettingsUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/user/settings", tags=["User Settings"])

BYOK_FIELDS = frozenset(
    {
        "llm_api_key",
        "llm_api_base_url",
        "llm_model",
        "embedding_api_key",
        "embedding_api_base_url",
        "embedding_model",
    }
)

ALLOWED_SETTINGS_FIELDS = frozenset(
    {
        "llm_api_key",
        "llm_api_base_url",
        "llm_model",
        "embedding_api_key",
        "embedding_api_base_url",
        "embedding_model",
        "email_notifications",
        "notify_on_mission_complete",
        "notify_on_critical_finding",
        "webhook_url",
        "prefer_mission_approval",
        "default_scan_mode",
        "default_report_format",
        "timezone",
        "share_training_data",
    }
)


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
        prefer_mission_approval=bool(getattr(prefs, "prefer_mission_approval", False)),
        default_scan_mode=prefs.default_scan_mode,
        default_report_format=prefs.default_report_format,
        timezone=prefs.timezone,
        share_training_data=prefs.share_training_data,
    )


async def _get_prefs(user_id: str, session: AsyncSession) -> UserPreferences | None:
    result = await session.execute(select(UserPreferences).where(UserPreferences.user_id == user_id))
    return result.scalar_one_or_none()


def _filter_byok_updates(updates: dict) -> dict:
    return {key: value for key, value in updates.items() if key in BYOK_FIELDS and value is not None}


async def _require_byok_feature_if_needed(
    user: User,
    session: AsyncSession,
    byok_updates: dict,
) -> None:
    if byok_updates:
        await check_feature_allowed(user, session, "byok")


async def _load_or_create_prefs(user_id: str, session: AsyncSession) -> UserPreferences:
    prefs = await _get_prefs(user_id, session)
    if prefs is None:
        prefs = UserPreferences(user_id=user_id)
        session.add(prefs)
    return prefs


def _apply_allowed_settings_fields(prefs: UserPreferences, updates: dict) -> None:
    for key, value in updates.items():
        if key in ALLOWED_SETTINGS_FIELDS:
            setattr(prefs, key, value)


async def _audit_with_swallow(
    session: AsyncSession,
    event_type: AuditEventType,
    user_id: str,
    details: dict,
    request: Request,
) -> None:
    with contextlib.suppress(OSError):
        await audit_log_event(
            session,
            event_type,
            user_id=user_id,
            details=details,
            request=request,
        )


async def _commit_and_audit_with_swallow(
    session: AsyncSession,
    event_type: AuditEventType,
    user_id: str,
    details: dict,
    request: Request,
    prefs: UserPreferences | None = None,
) -> None:
    await session.commit()
    if prefs is not None:
        await session.refresh(prefs)
    await _audit_with_swallow(
        session,
        event_type,
        user_id=user_id,
        details=details,
        request=request,
    )


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

    byok_updates = _filter_byok_updates(updates)
    await _require_byok_feature_if_needed(user, session, byok_updates)

    user_id = str(user.id)
    prefs = await _load_or_create_prefs(user_id, session)
    _apply_allowed_settings_fields(prefs, updates)

    event_type = AuditEventType.BYOK_CHANGED if byok_updates else AuditEventType.SETTINGS_CHANGED
    await _commit_and_audit_with_swallow(
        session,
        event_type,
        user_id=user_id,
        details={"action": "settings_updated", "fields": list(updates.keys())},
        request=request,
        prefs=prefs,
    )

    return _prefs_to_response(prefs)


@router.delete("/byok", status_code=200)
async def clear_byok(
    request: Request,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Clear all BYOK fields from the user's preferences."""
    user_id = str(user.id)
    prefs = await _get_prefs(user_id, session)
    if prefs is None:
        return {"detail": "No BYOK configuration to clear"}

    for field in BYOK_FIELDS:
        setattr(prefs, field, None)

    await _commit_and_audit_with_swallow(
        session,
        AuditEventType.BYOK_CHANGED,
        user_id=user_id,
        details={"action": "byok_cleared"},
        request=request,
    )

    return {"detail": "BYOK configuration cleared"}
