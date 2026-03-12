"""Admin server provisioning and pool management endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_active_user
from app.core.database import get_async_session
from app.core.rbac import Permission, require_permission
from app.models.audit_log import AuditEventType
from app.models.user import User
from app.services.system.audit import log_event as audit_log_event

logger = logging.getLogger("spectra.admin")

router = APIRouter()


# --- Pydantic request models ---


class ServerConnectionRequest(BaseModel):
    host: str
    port: int = 22
    username: str = "root"
    password: str | None = None
    private_key: str | None = None


class ProvisionRequest(ServerConnectionRequest):
    service_type: str
    service_port: int = 8080
    extra_env: dict[str, str] = Field(default_factory=dict)


class DeprovisionRequest(ServerConnectionRequest):
    pass


class UpdateServerNodeRequest(BaseModel):
    name: str | None = None
    url: str | None = None
    api_key: str | None = None
    is_active: bool | None = None
    is_primary: bool | None = None
    weight: int | None = Field(None, ge=1, le=100)
    max_capacity: int | None = Field(None, ge=1, le=1000)


@router.post("/api/admin/servers/verify")
async def verify_server_connection(
    body: ServerConnectionRequest,
    current_user: User = Depends(get_current_active_user),
    _perm=require_permission(Permission.MANAGE_SETTINGS),
):
    """Test SSH connectivity to a remote server without making changes."""
    from app.services.provisioning import ServerProvisioner
    from app.services.provisioning.provisioner import ServerConfig

    config = ServerConfig(
        host=body.host,
        port=body.port,
        username=body.username,
        password=body.password,
        private_key=body.private_key,
    )

    provisioner = ServerProvisioner()
    result = await provisioner.verify_connection(config)
    return result


@router.post("/api/admin/servers/provision", status_code=status.HTTP_202_ACCEPTED)
async def provision_server(
    body: ProvisionRequest,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    _perm=require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
):
    """Auto-install and configure a Spectra service on a remote server."""
    from app.services.provisioning import ServerProvisioner
    from app.services.provisioning.provisioner import ServerConfig

    if body.service_type != "sandbox_worker":
        raise HTTPException(400, f"Invalid service_type: {body.service_type}")

    config = ServerConfig(
        host=body.host,
        port=body.port,
        username=body.username,
        password=body.password,
        private_key=body.private_key,
        service_type=body.service_type,
        service_port=body.service_port,
        extra_env=body.extra_env,
    )

    provisioner = ServerProvisioner()
    result = await provisioner.provision(config)

    await audit_log_event(
        session,
        AuditEventType.SETTINGS_CHANGED,
        user_id=current_user.id,
        details={
            "action": "server_provisioned" if result.success else "server_provision_failed",
            "host": config.host,
            "service_type": body.service_type,
            "success": result.success,
            "error": result.error or None,
        },
        request=request,
    )

    return {
        "success": result.success,
        "service_url": result.service_url,
        "health_check_passed": result.health_check_passed,
        "logs": result.logs,
        "error": result.error,
    }


@router.post("/api/admin/servers/deprovision")
async def deprovision_server(
    body: DeprovisionRequest,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    _perm=require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
):
    """Remove a Spectra service from a remote server."""
    from app.services.provisioning import ServerProvisioner
    from app.services.provisioning.provisioner import ServerConfig

    config = ServerConfig(
        host=body.host,
        port=body.port,
        username=body.username,
        password=body.password,
        private_key=body.private_key,
        service_type="sandbox_worker",
    )

    provisioner = ServerProvisioner()
    result = await provisioner.deprovision(config)

    await audit_log_event(
        session,
        AuditEventType.SETTINGS_CHANGED,
        user_id=current_user.id,
        details={
            "action": "server_deprovisioned" if result.success else "server_deprovision_failed",
            "host": config.host,
            "service_type": config.service_type,
        },
        request=request,
    )

    return {
        "success": result.success,
        "logs": result.logs,
        "error": result.error,
    }


@router.get("/api/admin/servers")
async def list_server_nodes(
    service_type: str | None = None,
    session: AsyncSession = Depends(get_async_session),
    _admin: User = require_permission("admin"),  # type: ignore[assignment]
):
    """List all registered server nodes."""
    from app.services.scaling import get_pool_manager

    pool = get_pool_manager()
    return await pool.list_nodes(session, service_type=service_type)


@router.post("/api/admin/servers", status_code=201)
async def add_server_node(
    name: str = Body(...),
    service_type: str = Body(..., pattern=r"^(sandbox_worker|db_replica|storage)$"),
    url: str = Body(...),
    api_key: str | None = Body(None),
    is_primary: bool = Body(False),
    weight: int = Body(1, ge=1, le=100),
    max_capacity: int = Body(10, ge=1, le=1000),
    session: AsyncSession = Depends(get_async_session),
    _admin: User = require_permission("admin"),  # type: ignore[assignment]
):
    """Register a new server node in the pool."""
    from app.services.scaling import get_pool_manager

    pool = get_pool_manager()
    node = await pool.add_node(
        session,
        service_type,
        name,
        url,
        api_key=api_key,
        is_primary=is_primary,
        weight=weight,
        max_capacity=max_capacity,
    )
    await session.commit()
    logger.info("Server node added: %s (%s)", name, service_type)
    return node


@router.delete("/api/admin/servers/{node_id}")
async def remove_server_node(
    node_id: int,
    session: AsyncSession = Depends(get_async_session),
    _admin: User = require_permission("admin"),  # type: ignore[assignment]
):
    """Remove a server node from the pool."""
    from app.services.scaling import get_pool_manager

    pool = get_pool_manager()
    removed = await pool.remove_node(session, node_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Node not found")
    await session.commit()
    return {"status": "removed"}


@router.patch("/api/admin/servers/{node_id}")
async def update_server_node(
    node_id: int,
    body: UpdateServerNodeRequest,
    session: AsyncSession = Depends(get_async_session),
    _admin: User = require_permission("admin"),  # type: ignore[assignment]
):
    """Update a server node's configuration."""
    from app.services.scaling import get_pool_manager

    filtered = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    pool = get_pool_manager()
    node = await pool.update_node(session, node_id, **filtered)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    await session.commit()
    return node


@router.post("/api/admin/servers/health-check")
async def check_all_server_health(
    _admin: User = require_permission("admin"),  # type: ignore[assignment]
):
    """Run health checks on all active server nodes."""
    from app.services.scaling import get_pool_manager

    pool = get_pool_manager()
    results = await pool.health_check_all()
    return results
