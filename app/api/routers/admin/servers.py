"""Admin server provisioning and pool management endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_maker, get_async_session
from app.core.rbac import Permission, require_permission
from app.models.audit_log import AuditEventType
from app.models.user import User
from app.services.system.audit import log_event as audit_log_event

logger = logging.getLogger(__name__)

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
    service_type: str = "sandbox_worker"


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
    _perm: User = require_permission(Permission.MANAGE_SETTINGS),
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
    current_user: User = require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
):
    """Auto-install and configure a Spectra service on a remote server."""
    from app.services.provisioning import ServerProvisioner
    from app.services.provisioning.provisioner import ServerConfig

    valid_types = {"sandbox_worker", "app_worker", "tools_worker", "db_replica", "db_backup"}
    if body.service_type not in valid_types:
        raise HTTPException(400, f"Invalid service_type: {body.service_type}. Must be one of: {', '.join(sorted(valid_types))}")

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
    current_user: User = require_permission(Permission.MANAGE_SETTINGS),
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
        service_type=body.service_type,
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
            "service_type": body.service_type,
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
    _perm=require_permission(Permission.MANAGE_SETTINGS),
):
    """List all registered server nodes."""
    from app.services.scaling import get_pool_manager

    pool = get_pool_manager()
    return await pool.list_nodes(session, service_type=service_type)


@router.post("/api/admin/servers", status_code=201)
async def add_server_node(
    name: str = Body(...),
    service_type: str = Body(..., pattern=r"^(sandbox_worker|app_worker|tools_worker|db_replica|db_backup|storage)$"),
    url: str = Body(...),
    api_key: str | None = Body(None),
    is_primary: bool = Body(False),
    weight: int = Body(1, ge=1, le=100),
    max_capacity: int = Body(10, ge=1, le=1000),
    session: AsyncSession = Depends(get_async_session),
    _perm=require_permission(Permission.MANAGE_SETTINGS),
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
    _perm=require_permission(Permission.MANAGE_SETTINGS),
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
    _perm=require_permission(Permission.MANAGE_SETTINGS),
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
    _perm=require_permission(Permission.MANAGE_SETTINGS),
):
    """Run health checks on all active server nodes."""
    from app.services.scaling import get_pool_manager

    pool = get_pool_manager()
    results = await pool.health_check_all()
    return results


# --- Backups ---


@router.post("/api/admin/backups")
async def create_backup(
    request: Request,
    _perm: User = require_permission(Permission.MANAGE_SETTINGS),
):
    """Create a database backup."""
    from app.services.infrastructure.backup import BackupService

    svc = BackupService()
    result = await svc.create_backup()

    async with async_session_maker() as session:
        await audit_log_event(
            session,
            AuditEventType.BACKUP_CREATED,
            user_id=str(_perm.id),
            details={},
            request=request,
        )

    return result


@router.get("/api/admin/backups")
async def list_backups(
    _perm: User = require_permission(Permission.MANAGE_SETTINGS),
):
    """List all available backups."""
    from app.services.infrastructure.backup import BackupService

    svc = BackupService()
    return await svc.list_backups()


class RestoreRequest(BaseModel):
    backup_path: str


@router.post("/api/admin/backups/restore")
async def restore_backup(
    request: Request,
    body: RestoreRequest,
    _perm: User = require_permission(Permission.MANAGE_SETTINGS),
):
    """Restore database from a backup file."""
    from app.services.infrastructure.backup import BackupService

    svc = BackupService()
    result = await svc.restore_backup(body.backup_path)

    async with async_session_maker() as session:
        await audit_log_event(
            session,
            AuditEventType.BACKUP_RESTORED,
            user_id=str(_perm.id),
            details={},
            request=request,
        )

    return result


# --- Service Monitoring & Deployment ---


@router.get("/api/admin/services")
async def list_services(
    _perm=require_permission(Permission.MANAGE_SETTINGS),
):
    """List all registered services and their health status."""
    import httpx

    services = [
        {"name": "api", "type": "core", "port": 5000},
        {"name": "ai-svc", "type": "ai", "port": 5010},
        {"name": "scheduler", "type": "background", "port": None},
        {"name": "worker", "type": "tools", "port": None},
    ]

    results = []
    for svc in services:
        health_status = "unknown"
        if svc["port"]:
            for base in [f"http://{svc['name']}:{svc['port']}", f"http://localhost:{svc['port']}"]:
                try:
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        resp = await client.get(f"{base}/health")
                        health_status = "healthy" if resp.status_code == 200 else "unhealthy"
                        break
                except (OSError, RuntimeError, ConnectionError, TimeoutError):
                    health_status = "unreachable"

        results.append({
            "name": svc["name"],
            "type": svc["type"],
            "port": svc["port"],
            "status": health_status,
        })

    return {"services": results}


@router.get("/api/admin/services/nodes")
async def list_service_nodes(
    session: AsyncSession = Depends(get_async_session),
    _perm=require_permission(Permission.MANAGE_SETTINGS),
):
    """List all server nodes and their deployment status."""
    from sqlalchemy import select as sa_select

    from app.models.server_node import ServerNode

    nodes = (await session.execute(
        sa_select(ServerNode).order_by(ServerNode.created_at.desc())
    )).scalars().all()
    return {"nodes": [n.to_dict() for n in nodes]}


@router.post("/api/admin/services/nodes/{node_id}/deploy")
async def deploy_to_node(
    node_id: int,
    request: Request,
    services: list[str] | None = Body(None),
    harden: bool = Body(True),
    current_user: User = require_permission(Permission.MANAGE_SETTINGS),
    session: AsyncSession = Depends(get_async_session),
):
    """Deploy Spectra services to a remote server node."""
    from sqlalchemy import select as sa_select

    from app.models.server_node import ServerNode
    from app.services.infrastructure.deploy import ServerDeployer

    node = (await session.execute(
        sa_select(ServerNode).where(ServerNode.id == node_id)
    )).scalar_one_or_none()
    if not node:
        raise HTTPException(404, "Node not found")

    deployer = ServerDeployer()
    result = await deployer.deploy_to_server(
        server_id=str(node.id),
        hostname=node.url.split("://")[-1].split(":")[0].split("/")[0] if node.url else node.name,
        ssh_user=node.ssh_user,
        ssh_port=node.ssh_port,
        ssh_key=node.ssh_key_path,
        services=services,
        harden=harden,
    )

    # Update node status
    node.health_status = "healthy" if result.status.value == "complete" else "error"
    node.deployed_services = services or ["app", "ai-svc", "scheduler", "tools"]
    await session.commit()

    await audit_log_event(
        session,
        AuditEventType.SETTINGS_CHANGED,
        user_id=current_user.id,
        details={
            "action": "node_deployed" if result.status.value == "complete" else "node_deploy_failed",
            "node_id": node.id,
            "node_name": node.name,
        },
        request=request,
    )

    return {
        "status": result.status.value,
        "message": result.message,
        "logs": result.logs,
    }


@router.get("/api/admin/services/nodes/{node_id}/logs")
async def get_node_deployment_logs(
    node_id: int,
    _perm=require_permission(Permission.MANAGE_SETTINGS),
):
    """Get deployment logs for a server node."""
    from app.services.infrastructure.deploy import ServerDeployer

    deployer = ServerDeployer()
    logs = deployer.get_deployment_logs(str(node_id))
    return {"logs": logs}
