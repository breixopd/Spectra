"""VPN Management API Router.

Provides endpoints for uploading, managing, and connecting VPN configs
(WireGuard and OpenVPN) in the tools container.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.api.dependencies import get_current_active_user
from app.core.config import settings
from app.models.user import User
from app.services.tools.vpn import VPNManager

logger = logging.getLogger("spectra.api.vpn")

router = APIRouter(prefix="/vpn", tags=["VPN"])

_vpn_manager: VPNManager | None = None


def _get_vpn_manager() -> VPNManager:
    global _vpn_manager
    if _vpn_manager is None:
        _vpn_manager = VPNManager()
    return _vpn_manager


# --- Schemas ---


class VPNConfigResponse(BaseModel):
    name: str
    type: str
    path: str
    size: int


class VPNActionResponse(BaseModel):
    job_id: str
    config: str = ""
    type: str = ""
    action: str


class VPNConfigListItem(BaseModel):
    name: str
    type: str
    path: str
    size: int


# --- Endpoints ---


@router.post(
    "/configs",
    response_model=VPNConfigResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_vpn_config(
    file: UploadFile = File(...),
    name: str = Form(..., min_length=1, max_length=64),
    vpn_type: str = Form(..., pattern=r"^(wireguard|openvpn)$"),
    _user: User = Depends(get_current_active_user),
) -> VPNConfigResponse:
    """Upload a VPN configuration file."""
    if not settings.VPN_ENABLED:
        raise HTTPException(status_code=400, detail="VPN feature is disabled")
    try:
        # Read with size limit
        MAX_VPN_CONFIG_SIZE = 1024 * 1024  # 1MB
        content = await file.read(MAX_VPN_CONFIG_SIZE + 1)
        if len(content) > MAX_VPN_CONFIG_SIZE:
            raise HTTPException(status_code=400, detail="VPN config file too large (max 1MB)")
        mgr = _get_vpn_manager()
        result = await mgr.upload_config(name, content, vpn_type)
        return VPNConfigResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/configs", response_model=list[VPNConfigListItem])
async def list_vpn_configs(
    _user: User = Depends(get_current_active_user),
) -> list[VPNConfigListItem]:
    """List all saved VPN configurations."""
    mgr = _get_vpn_manager()
    configs = await mgr.list_configs()
    return [VPNConfigListItem(**c) for c in configs]


@router.delete("/configs/{name}", status_code=status.HTTP_200_OK)
async def delete_vpn_config(
    name: str,
    _user: User = Depends(get_current_active_user),
) -> dict:
    """Delete a saved VPN configuration."""
    mgr = _get_vpn_manager()
    try:
        deleted = await mgr.delete_config(name)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Config '{name}' not found")
    return {"deleted": True, "name": name}


@router.post("/connect/{name}", response_model=VPNActionResponse)
async def connect_vpn(
    name: str,
    _user: User = Depends(get_current_active_user),
) -> VPNActionResponse:
    """Connect to a VPN using the named configuration."""
    if not settings.VPN_ENABLED:
        raise HTTPException(status_code=400, detail="VPN feature is disabled")
    mgr = _get_vpn_manager()
    try:
        result = await mgr.connect(name)
        return VPNActionResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/disconnect/{name}", response_model=VPNActionResponse)
async def disconnect_vpn(
    name: str,
    _user: User = Depends(get_current_active_user),
) -> VPNActionResponse:
    """Disconnect from a VPN."""
    mgr = _get_vpn_manager()
    try:
        result = await mgr.disconnect(name)
        return VPNActionResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/status", response_model=VPNActionResponse)
async def vpn_status(
    _user: User = Depends(get_current_active_user),
) -> VPNActionResponse:
    """Get current VPN connection status."""
    mgr = _get_vpn_manager()
    result = await mgr.status()
    return VPNActionResponse(**result)


@router.post("/test", response_model=VPNActionResponse)
async def test_vpn_connection(
    _user: User = Depends(get_current_active_user),
) -> VPNActionResponse:
    """Test VPN connectivity."""
    mgr = _get_vpn_manager()
    result = await mgr.test_connection()
    return VPNActionResponse(**result)
