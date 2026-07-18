"""Runtime settings and AI gateway probe endpoints (SPA + admin)."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_api.api.dependencies import get_current_active_user, get_current_user
from spectra_api.api.schemas.system import SettingsUpdate
from spectra_api.authz import Permission, has_permission, require_permission
from spectra_api.services.system.settings_service import (
    apply_settings_update,
    get_ai_status_snapshot,
    get_current_settings,
)
from spectra_common.config import settings
from spectra_common.utils.url_validation import is_safe_url
from spectra_persistence.database import get_async_session
from spectra_persistence.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


async def _require_manage_settings_or_prebootstrap(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Allow gateway probe during install (no users yet); otherwise MANAGE_SETTINGS or superuser."""
    user_count = (await session.execute(select(func.count()).select_from(User))).scalar_one()
    if user_count == 0:
        return
    user = await get_current_user(request=request, session=session)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if user.is_superuser or has_permission(user.role, Permission.MANAGE_SETTINGS):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


@router.post("/api/settings")
async def update_settings(
    data: SettingsUpdate,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = require_permission(Permission.MANAGE_SETTINGS),
):
    """Update application settings."""
    try:
        return await apply_settings_update(data, db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/api/settings")
async def get_settings_api(
    _current_user: User = Depends(get_current_active_user),
):
    """Get current settings."""
    return get_current_settings()


@router.get("/api/ai/status")
async def get_ai_status(
    _current_user: User = Depends(get_current_active_user),
):
    """Get AI provider status and current model info."""
    return await get_ai_status_snapshot()


@router.post("/test-llm")
async def test_llm_connection(
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
):
    """Test TensorZero gateway connection."""
    gw_url = settings.TENSORZERO_GATEWAY_URL or "http://tensorzero:3000"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{gw_url}/health")
            if resp.status_code == 200:
                return {"status": "ok", "message": "TensorZero gateway is healthy"}
            return {"status": "error", "message": f"Gateway returned status {resp.status_code}"}
    except Exception as e:
        logger.warning("TensorZero gateway health check failed: %s", e)
        return {"status": "error", "message": "Cannot reach LLM gateway — check configuration"}


@router.post("/test-tz-gateway")
async def test_tz_gateway(
    request: Request,
    _access: None = Depends(_require_manage_settings_or_prebootstrap),
):
    """Test TensorZero gateway connection (setup page)."""
    body = await request.json()
    supplied_url = body.get("gateway_url")
    gw_url = supplied_url or settings.TENSORZERO_GATEWAY_URL or "http://tensorzero:3000"
    # The setup page is reachable before an account exists.  Only the known
    # in-cluster gateway may bypass public-DNS SSRF checks; user-supplied
    # addresses must resolve to a public HTTP(S) endpoint before probing.
    if supplied_url and not await is_safe_url(str(gw_url)):
        return {"success": False, "error": "Gateway URL is not a permitted public HTTP(S) endpoint"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{gw_url}/health")
            if resp.status_code == 200:
                return {"success": True}
            return {"success": False, "error": f"Gateway returned status {resp.status_code}"}
    except Exception as e:
        logger.warning("TensorZero gateway test failed for %s: %s", gw_url, e)
        return {"success": False, "error": "Cannot reach LLM gateway — check URL and try again"}
