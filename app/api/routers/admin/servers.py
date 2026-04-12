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
    service_type: str | None = Field(
        None,
        pattern=r"^(sandbox_worker|app_worker|tools_worker|db_replica|db_backup|storage)$",
    )


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
        raise HTTPException(
            400, f"Invalid service_type: {body.service_type}. Must be one of: {', '.join(sorted(valid_types))}"
        )

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
    request: Request,
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

    await audit_log_event(
        session,
        AuditEventType.SETTINGS_CHANGED,
        user_id=str(_perm.id),
        details={"action": "server_node_added", "node_name": name, "node_role": service_type},
        request=request,
    )

    logger.info("Server node added: %s (%s)", name, service_type)
    return node


@router.delete("/api/admin/servers/{node_id}")
async def remove_server_node(
    request: Request,
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

    await audit_log_event(
        session,
        AuditEventType.SETTINGS_CHANGED,
        user_id=str(_perm.id),
        details={"action": "server_node_removed", "node_id": str(node_id)},
        request=request,
    )

    return {"status": "removed"}


# Mapping from service_type to Swarm placement label role
_SERVICE_TYPE_TO_SWARM_ROLE: dict[str, str] = {
    "app_worker": "app",
    "sandbox_worker": "worker",
    "tools_worker": "worker",
    "db_replica": "db",
    "db_backup": "db",
    "storage": "storage",
}


async def _update_swarm_node_labels(
    node_name: str, old_service_type: str | None, new_service_type: str,
) -> str | None:
    """Update Docker Swarm node placement labels when service_type changes.

    Returns an error message on failure, or *None* on success / no-op.
    """
    import asyncio
    import subprocess

    new_role = _SERVICE_TYPE_TO_SWARM_ROLE.get(new_service_type)
    if not new_role:
        return None

    cmds: list[list[str]] = []
    # Remove old label if it differs
    old_role = _SERVICE_TYPE_TO_SWARM_ROLE.get(old_service_type or "")
    if old_role and old_role != new_role:
        cmds.append(["docker", "node", "update", "--label-rm", f"spectra.{old_role}", node_name])
    # Add new label
    cmds.append(["docker", "node", "update", "--label-add", f"spectra.{new_role}=true", node_name])

    for cmd in cmds:
        try:
            await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, text=True, timeout=30,
            )
        except Exception as exc:
            logger.warning("Swarm label update failed for %s: %s", node_name, exc)
            return f"DB updated but Swarm label update failed: {exc}"
    return None


@router.patch("/api/admin/servers/{node_id}")
async def update_server_node(
    request: Request,
    node_id: int,
    body: UpdateServerNodeRequest,
    session: AsyncSession = Depends(get_async_session),
    _perm=require_permission(Permission.MANAGE_SETTINGS),
):
    """Update a server node's configuration.

    When *service_type* is changed the endpoint also attempts to update
    Docker Swarm placement labels so the node is scheduled correctly.
    """
    from app.services.scaling import get_pool_manager

    filtered = dict(body.model_dump(exclude_unset=True).items())
    pool = get_pool_manager()

    # Capture old service_type before updating, for Swarm label diff
    old_service_type: str | None = None
    if "service_type" in filtered:
        old_node = await pool.get_node(session, node_id)
        if not old_node:
            raise HTTPException(status_code=404, detail="Node not found")
        old_service_type = old_node.get("service_type")

    node = await pool.update_node(session, node_id, **filtered)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    await session.commit()

    # Update Swarm labels when service_type changed
    swarm_warning: str | None = None
    new_service_type = filtered.get("service_type")
    if new_service_type and new_service_type != old_service_type:
        swarm_warning = await _update_swarm_node_labels(
            node["name"], old_service_type, new_service_type,
        )

    await audit_log_event(
        session,
        AuditEventType.SETTINGS_CHANGED,
        user_id=str(_perm.id),
        details={
            "action": "server_node_updated",
            "node_id": str(node_id),
            **(({"service_type_changed": f"{old_service_type} -> {new_service_type}"}) if new_service_type and new_service_type != old_service_type else {}),
        },
        request=request,
    )

    if swarm_warning:
        return {**node, "warning": swarm_warning}
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
    backup_id: str = Field(..., pattern=r"^backup_\d{8}_\d{6}$")


@router.post("/api/admin/backups/restore")
async def restore_backup(
    request: Request,
    body: RestoreRequest,
    _perm: User = require_permission(Permission.MANAGE_SETTINGS),
):
    """Restore database from an S3 backup."""
    from app.services.infrastructure.backup import BackupService

    svc = BackupService()
    result = await svc.restore_backup(body.backup_id)

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
        {"name": "api", "type": "core", "port": 5000, "aliases": ["app", "spectra_app"]},
        {"name": "ai-svc", "type": "ai", "port": 5010, "aliases": ["spectra_ai-svc"]},
        {"name": "scheduler", "type": "background", "port": 5011, "aliases": ["spectra_scheduler"]},
        {"name": "worker", "type": "tools", "port": None, "aliases": []},
    ]

    results = []
    for svc in services:
        health_status = "unknown"
        if svc["port"]:
            urls = [f"http://{alias}:{svc['port']}/api/health" for alias in [svc["name"]] + svc.get("aliases", [])]
            urls.append(f"http://localhost:{svc['port']}/api/health")
            for url in urls:
                try:
                    async with httpx.AsyncClient(timeout=3.0) as client:
                        resp = await client.get(url)
                        health_status = "healthy" if resp.status_code == 200 else "unhealthy"
                        break
                except Exception:
                    health_status = "unreachable"

        results.append(
            {
                "name": svc["name"],
                "type": svc["type"],
                "port": svc["port"],
                "status": health_status,
            }
        )

    return {"services": results}


@router.get("/api/admin/services/nodes")
async def list_service_nodes(
    session: AsyncSession = Depends(get_async_session),
    _perm=require_permission(Permission.MANAGE_SETTINGS),
):
    """List all server nodes and their deployment status."""
    from sqlalchemy import select as sa_select

    from app.models.server_node import ServerNode

    nodes = (await session.execute(sa_select(ServerNode).order_by(ServerNode.created_at.desc()))).scalars().all()
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

    node = (await session.execute(sa_select(ServerNode).where(ServerNode.id == node_id))).scalar_one_or_none()
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


@router.get("/api/admin/scaling/metrics")
async def get_scaling_metrics(
    queue_name: str = "default",
    _perm=require_permission(Permission.MANAGE_SETTINGS),
):
    """Return full cluster metrics: per-service CPU/memory, system resources, queue stats, and node health."""
    from app.services.scaling.metrics_collector import MetricsCollector

    collector = MetricsCollector()
    cluster = await collector.collect_all()
    return {
        "timestamp": cluster.timestamp.isoformat(),
        "services": {
            name: {
                "replicas": svc.replicas,
                "desired_replicas": svc.desired_replicas,
                "cpu_percent": round(svc.cpu_percent, 2),
                "memory_mb": round(svc.memory_mb, 1),
                "healthy": svc.healthy,
                "failed_tasks": svc.failed_tasks,
                "running_tasks": svc.running_tasks,
            }
            for name, svc in cluster.services.items()
        },
        "system": {
            "cpu_percent": round(cluster.system.cpu_percent, 1),
            "memory_percent": round(cluster.system.memory_percent, 1),
            "memory_available_mb": round(cluster.system.memory_available_mb, 0),
            "disk_percent": round(cluster.system.disk_percent, 1),
            "disk_free_gb": round(cluster.system.disk_free_gb, 1),
            "load_avg_1m": round(cluster.system.load_avg_1m, 2),
            "load_avg_5m": round(cluster.system.load_avg_5m, 2),
        },
        "queue": {
            "depth": cluster.queue.depth,
            "in_progress": cluster.queue.in_progress,
            "completed": cluster.queue.completed,
            "avg_wait_secs": round(cluster.queue.avg_wait_secs, 1),
            "oldest_job_secs": round(cluster.queue.oldest_job_secs, 1),
        },
        "nodes": {
            "total": cluster.nodes_total,
            "healthy": cluster.nodes_healthy,
            "unhealthy": cluster.nodes_unhealthy,
        },
    }


@router.get("/api/admin/scaling/status")
async def get_scaling_status(
    _perm=require_permission(Permission.MANAGE_SETTINGS),
):
    """Get auto-scaling status, current policies, queue metrics, and current config values."""
    from app.core.config import get_settings as _get_settings
    from app.core.queue import queue_metrics

    settings = _get_settings()
    result: dict = {"enabled": settings.AUTOSCALE_ENABLED}

    # Always include current config values so the admin UI can populate the form
    result["config"] = {
        "autoscale_enabled": settings.AUTOSCALE_ENABLED,
        "autoscale_worker_min": getattr(settings, "AUTOSCALE_WORKER_MIN", 1),
        "autoscale_worker_max": getattr(settings, "AUTOSCALE_WORKER_MAX", 10),
        "autoscale_api_min": getattr(settings, "AUTOSCALE_API_MIN", 2),
        "autoscale_api_max": getattr(settings, "AUTOSCALE_API_MAX", 8),
        "autoscale_ai_max": getattr(settings, "AUTOSCALE_AI_MAX", 4),
        "autoscale_queue_threshold": getattr(settings, "AUTOSCALE_QUEUE_THRESHOLD", 5),
        "autoscale_cooldown_secs": getattr(settings, "AUTOSCALE_COOLDOWN_SECS", 300),
        "autoscale_idle_secs": getattr(settings, "AUTOSCALE_IDLE_SECS", 600),
        "autoscale_cpu_up_threshold": getattr(settings, "AUTOSCALE_CPU_UP_THRESHOLD", 75),
        "autoscale_cpu_down_threshold": getattr(settings, "AUTOSCALE_CPU_DOWN_THRESHOLD", 25),
        "infra_monitor_enabled": getattr(settings, "INFRA_MONITOR_ENABLED", True),
        "infra_monitor_pg_threshold": getattr(settings, "INFRA_MONITOR_PG_THRESHOLD", 80),
        "infra_monitor_redis_threshold": getattr(settings, "INFRA_MONITOR_REDIS_THRESHOLD", 85),
        "infra_monitor_storage_threshold": getattr(settings, "INFRA_MONITOR_STORAGE_THRESHOLD", 90),
    }

    from app.services.scaling.auto_scaler import AutoScaler

    scaler = AutoScaler(settings)
    result["scaler"] = scaler.get_status()

    stats = await queue_metrics()
    result["queue"] = stats
    return result


@router.get("/api/admin/resources/capacity")
async def get_resource_capacity(
    _perm=require_permission(Permission.MANAGE_SETTINGS),
):
    """Auto-calculated resource capacity for this node and network, including live system metrics."""
    from app.core.config import get_settings as _get_settings
    from app.services.resource_manager import ResourceManager
    from app.services.scaling.metrics_collector import MetricsCollector

    s = _get_settings()
    local = await ResourceManager.get_node_resources()
    capacity = ResourceManager.calculate_node_capacity(
        local["total_memory_mb"], local["cpu_cores"], s.SERVICE_MODE
    )

    # Collect live system metrics
    collector = MetricsCollector()
    system = (await collector.collect_all()).system

    return {
        "local": {**local, **capacity},
        "service_mode": s.SERVICE_MODE,
        "system": {
            "cpu_percent": round(system.cpu_percent, 1),
            "memory_percent": round(system.memory_percent, 1),
            "memory_available_mb": round(system.memory_available_mb, 0),
            "disk_percent": round(system.disk_percent, 1),
            "disk_free_gb": round(system.disk_free_gb, 1),
            "load_avg_1m": round(system.load_avg_1m, 2),
            "load_avg_5m": round(system.load_avg_5m, 2),
        },
    }


# --- Scaling Configuration ---


class ScalingConfigUpdate(BaseModel):
    """Schema for updating auto-scaling configuration."""

    autoscale_enabled: bool | None = None
    autoscale_worker_min: int | None = Field(None, ge=1, le=20)
    autoscale_worker_max: int | None = Field(None, ge=1, le=50)
    autoscale_api_min: int | None = Field(None, ge=1, le=10)
    autoscale_api_max: int | None = Field(None, ge=1, le=20)
    autoscale_ai_max: int | None = Field(None, ge=1, le=10)
    autoscale_queue_threshold: int | None = Field(None, ge=1, le=100)
    autoscale_cooldown_secs: int | None = Field(None, ge=30, le=3600)
    autoscale_idle_secs: int | None = Field(None, ge=60, le=7200)
    autoscale_cpu_up_threshold: int | None = Field(None, ge=50, le=99)
    autoscale_cpu_down_threshold: int | None = Field(None, ge=5, le=50)
    infra_monitor_enabled: bool | None = None
    infra_monitor_pg_threshold: int | None = Field(None, ge=50, le=99)
    infra_monitor_redis_threshold: int | None = Field(None, ge=50, le=99)
    infra_monitor_storage_threshold: int | None = Field(None, ge=50, le=99)


# Map from ScalingConfigUpdate field names to DB config keys
_SCALING_FIELD_TO_DB_KEY: dict[str, tuple[str, str]] = {
    "autoscale_enabled": ("AUTOSCALE_ENABLED", "bool"),
    "autoscale_worker_min": ("AUTOSCALE_WORKER_MIN", "int"),
    "autoscale_worker_max": ("AUTOSCALE_WORKER_MAX", "int"),
    "autoscale_api_min": ("AUTOSCALE_API_MIN", "int"),
    "autoscale_api_max": ("AUTOSCALE_API_MAX", "int"),
    "autoscale_ai_max": ("AUTOSCALE_AI_MAX", "int"),
    "autoscale_queue_threshold": ("AUTOSCALE_QUEUE_THRESHOLD", "int"),
    "autoscale_cooldown_secs": ("AUTOSCALE_COOLDOWN_SECS", "int"),
    "autoscale_idle_secs": ("AUTOSCALE_IDLE_SECS", "int"),
    "autoscale_cpu_up_threshold": ("AUTOSCALE_CPU_UP_THRESHOLD", "int"),
    "autoscale_cpu_down_threshold": ("AUTOSCALE_CPU_DOWN_THRESHOLD", "int"),
    "infra_monitor_enabled": ("INFRA_MONITOR_ENABLED", "bool"),
    "infra_monitor_pg_threshold": ("INFRA_MONITOR_PG_THRESHOLD", "int"),
    "infra_monitor_redis_threshold": ("INFRA_MONITOR_REDIS_THRESHOLD", "int"),
    "infra_monitor_storage_threshold": ("INFRA_MONITOR_STORAGE_THRESHOLD", "int"),
}


@router.get("/api/admin/scaling/config")
async def get_scaling_config(
    _perm=require_permission(Permission.MANAGE_SETTINGS),
):
    """Return current auto-scaling configuration."""
    from app.core.config import get_settings as _get_settings
    from app.services.scaling.auto_scaler import AutoScaler

    settings = _get_settings()
    scaler = AutoScaler(settings)
    return {
        "autoscale_enabled": scaler.get_config_snapshot().get("scaling.enabled", True),
        "policies": {
            name: {
                "min_replicas": p.min_replicas,
                "max_replicas": p.max_replicas,
                "scale_up_threshold": p.scale_up_threshold,
                "scale_down_threshold": p.scale_down_threshold,
                "scale_up_queue_depth": p.scale_up_queue_depth,
                "cooldown_secs": p.cooldown_secs,
            }
            for name, p in scaler.policies.items()
        },
        "infra_monitor": {
            "enabled": bool(scaler.infra_monitors),
        },
    }


@router.put("/api/admin/scaling/config")
async def update_scaling_config(
    update: ScalingConfigUpdate,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = require_permission(Permission.MANAGE_SETTINGS),
):
    """Update auto-scaling configuration. Changes take effect on next evaluation cycle."""
    from app.services.system.runtime_settings import (
        hydrate_runtime_settings_from_db,
        upsert_system_config_values,
    )

    db_values: dict[str, tuple[str, bool]] = {}
    for field_name, value in update.model_dump(exclude_unset=True).items():
        mapping = _SCALING_FIELD_TO_DB_KEY.get(field_name)
        if mapping is None:
            continue
        db_key, kind = mapping
        if kind == "bool":
            db_values[db_key] = (str(value).lower(), False)
        else:
            db_values[db_key] = (str(value), False)

    if not db_values:
        raise HTTPException(status_code=400, detail="No valid scaling fields provided")

    await upsert_system_config_values(session, db_values)
    await session.commit()
    await hydrate_runtime_settings_from_db(session, persist_normalized=True, commit=True, reset_caches=False)

    await audit_log_event(
        session,
        AuditEventType.SETTINGS_CHANGED,
        user_id=current_user.id,
        details={"action": "scaling_config_updated", "fields": list(db_values.keys())},
        request=request,
    )

    return {"status": "updated", "message": "Scaling configuration updated — takes effect on next evaluation cycle"}


# --- Scaling Actions ---


class ScalingActionRequest(BaseModel):
    """Schema for executing a scaling action on a service."""

    action: str = Field(..., pattern=r"^(scale_up|scale_down|restart|heal)$")
    service: str


_ALLOWED_SCALING_SERVICES = frozenset({
    "spectra_app",
    "spectra_worker",
    "spectra_ai-svc",
    "spectra_scheduler",
    "spectra_caddy",
})


async def _run_docker_cmd(cmd: list[str], timeout: int = 30) -> tuple[bool, str]:
    """Run a Docker command locally, return (success, output)."""
    import asyncio
    import subprocess as sp

    try:
        result = await asyncio.to_thread(
            sp.run, cmd, capture_output=True, text=True, timeout=timeout,
        )
        output = result.stdout.strip() or result.stderr.strip()
        return result.returncode == 0, output
    except Exception as e:
        return False, str(e)


_NOT_MANAGER_MARKERS = ("not a swarm manager", "cannot connect to the docker daemon")


async def _proxy_scaling_to_scheduler(action: str, service: str) -> dict | None:
    """Forward a scaling action to the scheduler service (runs on Swarm manager)."""
    import httpx

    from app.core.config import get_settings as _gs

    settings = _gs()
    url = f"{settings.SCHEDULER_SERVICE_URL}/internal/scaling/action"
    secret = settings.SERVICE_AUTH_SECRET.get_secret_value()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                json={"action": action, "service": service},
                headers={"X-Service-Auth": secret},
            )
            if resp.status_code == 200:
                return resp.json()
            logger.warning("Scheduler proxy returned %d: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.warning("Failed to proxy scaling action to scheduler: %s", exc)
    return None


async def _execute_docker_scaling(action: str, service: str) -> tuple[bool, str]:
    """Run a Docker scaling command locally, falling back to the scheduler on non-manager nodes."""
    if action in ("scale_up", "scale_down"):
        ok, out = await _run_docker_cmd(
            ["docker", "service", "inspect", service, "--format", "{{.Spec.Mode.Replicated.Replicas}}"],
            timeout=10,
        )
        current = int(out) if ok and out.isdigit() else 1
        new_count = current + 1 if action == "scale_up" else max(1, current - 1)
        ok, out = await _run_docker_cmd(
            ["docker", "service", "scale", f"{service}={new_count}"],
            timeout=30,
        )
        return ok, out

    elif action == "restart":
        return await _run_docker_cmd(
            ["docker", "service", "update", "--force", service],
            timeout=60,
        )

    return False, f"Unknown action: {action}"


@router.post("/api/admin/scaling/action")
async def execute_scaling_action(
    body: ScalingActionRequest,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = require_permission(Permission.MANAGE_SETTINGS),
):
    """Execute a scaling action: scale_up, scale_down, restart, or heal a service."""
    if body.service not in _ALLOWED_SCALING_SERVICES:
        raise HTTPException(
            status_code=400,
            detail=f"Service must be one of: {', '.join(sorted(_ALLOWED_SCALING_SERVICES))}",
        )

    action = body.action
    service = body.service

    # Heal bypasses Docker commands entirely
    if action == "heal":
        from app.services.scaling.auto_scaler import AutoScaler
        from app.services.scaling.metrics_collector import MetricsCollector

        collector = MetricsCollector()
        metrics = await collector.collect_all()
        from app.core.config import get_settings as _get_settings
        scaler = AutoScaler(_get_settings())
        actions = await scaler._auto_heal(metrics)

        await audit_log_event(
            session,
            AuditEventType.SETTINGS_CHANGED,
            user_id=current_user.id,
            details={"action": "scaling_heal", "service": service, "heal_actions": actions},
            request=request,
        )
        return {"success": bool(actions), "action": action, "service": service, "actions": actions}

    # Try Docker command locally first
    success, output = await _execute_docker_scaling(action, service)

    # If this node is not the Swarm manager, proxy through the scheduler
    if not success and any(m in output.lower() for m in _NOT_MANAGER_MARKERS):
        logger.info("Not a swarm manager — proxying scaling action to scheduler")
        proxied = await _proxy_scaling_to_scheduler(action, service)
        if proxied is not None:
            await audit_log_event(
                session,
                AuditEventType.SETTINGS_CHANGED,
                user_id=current_user.id,
                details={"action": f"scaling_{action}", "service": service, "proxied": True},
                request=request,
            )
            return proxied

    await audit_log_event(
        session,
        AuditEventType.SETTINGS_CHANGED,
        user_id=current_user.id,
        details={"action": f"scaling_{action}", "service": service},
        request=request,
    )

    return {"success": success, "action": action, "service": service}


# --- Image Update Status & Manual Trigger ---


@router.get("/api/admin/updates/status")
async def get_update_status(
    _perm=require_permission(Permission.MANAGE_SETTINGS),
):
    """Get current image update status for all managed services."""
    import httpx

    from app.core.config import get_settings as _gs

    settings = _gs()
    url = f"{settings.SCHEDULER_SERVICE_URL}/internal/updates/status"
    secret = settings.SERVICE_AUTH_SECRET.get_secret_value()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers={"X-Service-Auth": secret})
            if resp.status_code == 200:
                return resp.json()
    except Exception as exc:
        logger.warning("Failed to fetch update status from scheduler: %s", exc)
    raise HTTPException(status_code=502, detail="Could not reach scheduler for update status")


class UpdateApplyRequest(BaseModel):
    service: str | None = None
    all: bool = False


@router.post("/api/admin/updates/apply")
async def trigger_update(
    body: UpdateApplyRequest,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = require_permission(Permission.MANAGE_SETTINGS),
):
    """Manually trigger an image update for a service (or all managed services)."""
    import httpx

    from app.core.config import get_settings as _gs

    settings = _gs()
    url = f"{settings.SCHEDULER_SERVICE_URL}/internal/updates/apply"
    secret = settings.SERVICE_AUTH_SECRET.get_secret_value()

    payload: dict = {}
    if body.service and not body.all:
        payload["service"] = body.service

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(url, json=payload, headers={"X-Service-Auth": secret})
            if resp.status_code == 200:
                result = resp.json()
                await audit_log_event(
                    session,
                    AuditEventType.SETTINGS_CHANGED,
                    user_id=current_user.id,
                    details={
                        "action": "manual_image_update",
                        "service": body.service or "all",
                    },
                    request=request,
                )
                return result
    except Exception as exc:
        logger.warning("Failed to proxy update apply to scheduler: %s", exc)
    raise HTTPException(status_code=502, detail="Could not reach scheduler to apply update")
