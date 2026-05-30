"""VPN Management API Router.

Provides endpoints for uploading, managing, and connecting VPN configs
(WireGuard and OpenVPN) in the tools container.
"""

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_api.api.dependencies import check_feature_allowed, get_current_active_user
from spectra_api.authz import Permission, require_permission
from spectra_auth.rate_limit import RateLimits, limiter
from spectra_common.config import settings
from spectra_persistence.database import get_async_session
from spectra_persistence.models.user import User
from spectra_tools.vpn import VPNManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vpn", tags=["VPN"])

VPN_NAME_PATTERN = r"^[a-zA-Z0-9_-]+$"

DANGEROUS_OPENVPN_DIRECTIVES = [
    "up ",
    "down ",
    "client-connect",
    "client-disconnect",
    "learn-address",
    "auth-user-pass-verify",
    "tls-verify",
    "ipchange",
    "route-up",
    "route-pre-down",
    "script-security",
]

_vpn_manager: VPNManager | None = None


def _get_vpn_manager() -> VPNManager:
    global _vpn_manager
    if _vpn_manager is None:
        _vpn_manager = VPNManager()
    return _vpn_manager


def _scoped_name(user: User, name: str) -> str:
    """Prefix config name with user_id for isolation."""
    return f"u_{user.id}_{name}"


def _unscoped_name(user: User, scoped: str) -> str:
    """Strip user_id prefix from config name."""
    prefix = f"u_{user.id}_"
    return scoped[len(prefix) :] if scoped.startswith(prefix) else scoped


# --- Schemas ---


class VPNConfigResponse(BaseModel):
    name: str
    type: str
    path: str = ""
    size: int = 0


class VPNActionResponse(BaseModel):
    job_id: str
    config: str = ""
    type: str = ""
    action: str


class VPNConfigListItem(BaseModel):
    name: str
    type: str
    path: str = ""
    size: int = 0


# --- Endpoints ---


@router.post(
    "/configs",
    response_model=VPNConfigResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(RateLimits.VPN_WRITE)
async def upload_vpn_config(
    request: Request,
    file: UploadFile = File(...),
    name: str = Form(..., min_length=1, max_length=64, pattern=VPN_NAME_PATTERN),
    vpn_type: str = Form(..., pattern=r"^(wireguard|openvpn)$"),
    _user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> VPNConfigResponse:
    """Upload a VPN configuration file."""
    if not settings.VPN_ENABLED:
        raise HTTPException(status_code=400, detail="VPN feature is disabled")
    try:
        await check_feature_allowed(_user, db, "vpn_support")
    except HTTPException:
        raise HTTPException(
            status_code=403,
            detail="VPN support requires Pro plan or higher. Upgrade at /billing/plans",
        )
    try:
        # Read with size limit
        MAX_VPN_CONFIG_SIZE = 1024 * 1024  # 1MB
        content = await file.read(MAX_VPN_CONFIG_SIZE + 1)
        if len(content) > MAX_VPN_CONFIG_SIZE:
            raise HTTPException(status_code=400, detail="VPN config file too large (max 1MB)")

        # Reject OpenVPN configs with dangerous directives that allow arbitrary command execution
        if vpn_type == "openvpn":
            content_lower = content.decode(errors="replace").lower()
            for directive in DANGEROUS_OPENVPN_DIRECTIVES:
                if directive in content_lower:
                    raise HTTPException(
                        status_code=400,
                        detail=f"OpenVPN config contains forbidden directive: {directive.strip()}",
                    )

        mgr = _get_vpn_manager()
        result = await mgr.upload_config(_scoped_name(_user, name), content, vpn_type)
        result["name"] = name  # Return user-facing name
        return VPNConfigResponse(**result)
    except ValueError as e:
        logger.warning("VPN config upload validation failed: %s", e)
        raise HTTPException(status_code=422, detail="Invalid VPN configuration")


@router.get("/configs", response_model=list[VPNConfigListItem])
@limiter.limit(RateLimits.VPN_READ)
async def list_vpn_configs(
    request: Request,
    _user: User = Depends(get_current_active_user),
) -> list[VPNConfigListItem]:
    """List VPN configurations owned by the current user."""
    mgr = _get_vpn_manager()
    all_configs = await mgr.list_configs()
    prefix = f"u_{_user.id}_"
    user_configs = [c for c in all_configs if c.get("name", "").startswith(prefix)]
    for c in user_configs:
        c["name"] = _unscoped_name(_user, c["name"])
    return [VPNConfigListItem(**c) for c in user_configs]


@router.delete("/configs/{name}", status_code=status.HTTP_200_OK)
@limiter.limit(RateLimits.VPN_WRITE)
async def delete_vpn_config(
    request: Request,
    name: str = Path(..., pattern=VPN_NAME_PATTERN),
    _user: User = Depends(get_current_active_user),
) -> dict:
    """Delete a saved VPN configuration."""
    mgr = _get_vpn_manager()
    try:
        deleted = await mgr.delete_config(_scoped_name(_user, name))
    except ValueError as e:
        logger.warning("VPN config delete failed for %s: %s", name, e)
        raise HTTPException(status_code=422, detail="Failed to delete VPN configuration")
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Config '{name}' not found")
    return {"deleted": True, "name": name}


@router.post("/connect/{name}", response_model=VPNActionResponse)
@limiter.limit(RateLimits.VPN_WRITE)
async def connect_vpn(
    request: Request,
    name: str = Path(..., pattern=VPN_NAME_PATTERN),
    _user: User = require_permission(Permission.VIEW_MONITORING),
) -> VPNActionResponse:
    """Connect the shared VPN runtime using the caller's saved configuration."""
    if not settings.VPN_ENABLED:
        raise HTTPException(status_code=400, detail="VPN feature is disabled")
    mgr = _get_vpn_manager()
    try:
        result = await mgr.connect(_scoped_name(_user, name))
        return VPNActionResponse(**result)
    except ValueError as e:
        logger.warning("VPN connect failed for %s: %s", name, e)
        raise HTTPException(status_code=422, detail="VPN connection failed")


@router.post("/disconnect/{name}", response_model=VPNActionResponse)
@limiter.limit(RateLimits.VPN_WRITE)
async def disconnect_vpn(
    request: Request,
    name: str = Path(..., pattern=VPN_NAME_PATTERN),
    _user: User = require_permission(Permission.VIEW_MONITORING),
) -> VPNActionResponse:
    """Disconnect the shared VPN runtime from the caller's saved configuration."""
    mgr = _get_vpn_manager()
    try:
        result = await mgr.disconnect(_scoped_name(_user, name))
        return VPNActionResponse(**result)
    except ValueError as e:
        logger.warning("VPN disconnect failed for %s: %s", name, e)
        raise HTTPException(status_code=422, detail="VPN disconnect failed")


@router.get("/status", response_model=VPNActionResponse)
@limiter.limit(RateLimits.VPN_READ)
async def vpn_status(
    request: Request,
    _user: User = require_permission(Permission.VIEW_MONITORING),
) -> VPNActionResponse:
    """Get shared VPN runtime status."""
    mgr = _get_vpn_manager()
    result = await mgr.status()
    return VPNActionResponse(**result)


@router.post("/test", response_model=VPNActionResponse)
@limiter.limit(RateLimits.VPN_WRITE)
async def test_vpn_connection(
    request: Request,
    _user: User = require_permission(Permission.VIEW_MONITORING),
) -> VPNActionResponse:
    """Test shared VPN runtime connectivity."""
    mgr = _get_vpn_manager()
    result = await mgr.test_connection()
    return VPNActionResponse(**result)
