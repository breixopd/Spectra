"""Health, internal admin, and scaling HTTP routes for the scheduler service."""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from spectra_auth.rate_limit import RateLimits, limiter
from spectra_common.tasks import create_safe_task
from spectra_scheduler import state as scheduler_state
from spectra_scheduler.leader import leader_election_loop
from spectra_scheduler.locks import _SCHEDULER_TASK_SPECS
from spectra_scheduler.service import SchedulerService
from spectra_tools.sandbox import get_sandbox_pool, set_sandbox_pool

logger = logging.getLogger("spectra_scheduler")

_VPN_CONFIG_NAME_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,159}$"


class SandboxCreateRequest(BaseModel):
    """Authenticated API request for scheduler-owned sandbox creation."""

    mission_id: UUID
    resource_tier: str = Field(default="medium", min_length=1, max_length=64, pattern=r"^[a-zA-Z][a-zA-Z0-9_-]*$")
    user_id: UUID | None = None
    vpn_config_name: str | None = Field(default=None, pattern=_VPN_CONFIG_NAME_PATTERN)


def latency_ms(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 1)


def task_health_details(scheduler: SchedulerService) -> tuple[dict[str, dict[str, Any]], bool]:
    """Describe scheduler loops, including supervised recovery state."""
    details: dict[str, dict[str, Any]] = {}
    degraded = False
    restart_counts = getattr(scheduler, "_task_restarts", {})
    last_failures = getattr(scheduler, "_task_last_failure", {})
    for task_name, _method_name in _SCHEDULER_TASK_SPECS:
        task = scheduler._named_tasks.get(task_name)
        if task is None:
            details[task_name] = {"state": "missing"}
            degraded = True
        elif task.done():
            details[task_name] = {"state": "dead"}
            degraded = True
        elif task_name in restart_counts:
            details[task_name] = {
                "state": "recovering",
                "restart_count": restart_counts[task_name],
                "last_failure": last_failures.get(task_name, "unknown"),
            }
            degraded = True
        else:
            details[task_name] = {"state": "alive"}
    return details, degraded


def sandbox_payload(info: Any) -> dict[str, Any]:
    """Serialize a sandbox handle without exposing Docker internals."""
    created_at = getattr(info, "created_at", None)
    return {
        "container_id": info.container_id,
        "container_name": info.container_name,
        "mission_id": info.mission_id,
        "queue_name": info.queue_name,
        "status": info.status,
        "image": info.image,
        "resource_tier": info.resource_tier,
        "network_id": info.network_id,
        "created_at": created_at.isoformat() if created_at else None,
    }


async def _vpn_config_path(config_name: str | None) -> str | None:
    """Resolve a validated VPN config name locally on the scheduler host."""
    if not config_name:
        return None
    if not re.fullmatch(_VPN_CONFIG_NAME_PATTERN, config_name):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid VPN config name")
    from spectra_tools.vpn import VPNManager

    local_path = await VPNManager()._download_to_local(config_name)
    if local_path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="VPN config not found")
    return str(local_path)


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    try:
        from spectra_scaling.pool_manager import get_pool_manager

        pool = get_pool_manager()
        node = await pool.register_local_node()
        logger.info("Local pool node ready: %s (id=%s)", node.get("name"), node.get("id"))
    except Exception:
        logger.warning("Failed to auto-register local node — continuing", exc_info=True)

    try:
        from spectra_tools.sandbox import SandboxPool

        sandbox_pool = SandboxPool()
        set_sandbox_pool(sandbox_pool)
        if sandbox_pool.available:
            reconciled = await sandbox_pool.reconcile_orphans()
            logger.info("Scheduler sandbox controller ready (reconciled=%d)", reconciled)
        else:
            logger.warning("Scheduler sandbox controller unavailable: Docker not accessible")
    except (OSError, RuntimeError) as exc:
        logger.warning("Scheduler sandbox controller initialization failed: %s", exc)

    sched = SchedulerService()
    scheduler_state._scheduler_instance = sched
    task = create_safe_task(leader_election_loop(sched), name="leader_election")
    yield
    await sched.stop()
    set_sandbox_pool(None)
    scheduler_state._scheduler_instance = None
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="Spectra Scheduler", version="1.0.0", lifespan=lifespan)

from spectra_common.config import settings as _settings
from spectra_infra.di.service_auth import ServiceAuthMiddleware

_secret = _settings.SERVICE_AUTH_SECRET.get_secret_value()
app.add_middleware(ServiceAuthMiddleware, secret=_secret)


@app.get("/healthz")
async def healthz():
    return {"status": "alive", "service": "scheduler"}


@app.get("/health")
async def health(response: Response):
    if scheduler_state._scheduler_instance is None:
        return {"status": "starting", "service": "scheduler"}
    result = scheduler_state._scheduler_instance.health()
    result["service"] = "scheduler"
    if result.get("status") == "degraded":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result


@app.get("/v1/sandboxes/health")
async def sandbox_health():
    """Return scheduler-owned sandbox controller health (service-auth protected)."""
    pool = get_sandbox_pool()
    if pool is None or not pool.available:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Sandbox controller unavailable")
    return await pool.health_check()


@app.post("/v1/sandboxes", status_code=status.HTTP_201_CREATED)
async def create_sandbox(payload: SandboxCreateRequest):
    """Create an isolated mission sandbox on the only Docker-capable service."""
    pool = get_sandbox_pool()
    if pool is None or not pool.available:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Sandbox controller unavailable")
    mission_id = str(payload.mission_id)
    try:
        info = await pool.create(
            mission_id,
            resource_tier=payload.resource_tier,
            user_id=str(payload.user_id) if payload.user_id else None,
            vpn_config_path=await _vpn_config_path(payload.vpn_config_name),
        )
    except HTTPException:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("Scheduler sandbox creation rejected for mission %s: %s", mission_id[:8], exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Sandbox creation unavailable") from exc
    return sandbox_payload(info)


@app.get("/v1/sandboxes/{mission_id}")
async def get_sandbox(mission_id: UUID):
    """Return a mission sandbox state from the scheduler control plane."""
    pool = get_sandbox_pool()
    if pool is None or not pool.available:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Sandbox controller unavailable")
    info = await pool.get(str(mission_id))
    if info is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sandbox not found")
    return sandbox_payload(info)


@app.delete("/v1/sandboxes/{mission_id}")
async def destroy_sandbox(mission_id: UUID):
    """Destroy one mission sandbox through the scheduler control plane."""
    pool = get_sandbox_pool()
    if pool is None or not pool.available:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Sandbox controller unavailable")
    await pool.destroy(str(mission_id))
    return {"status": "destroyed", "mission_id": str(mission_id)}


@app.get("/health/deep")
async def health_deep(response: Response):
    checks: dict[str, Any] = {}
    overall = "healthy"

    start = time.monotonic()
    try:
        from spectra_persistence.database import async_session_maker

        async with async_session_maker() as session:
            row = await session.execute(text("SELECT COUNT(*) FROM missions LIMIT 1"))
            count = row.scalar_one()
            checks["database"] = {"status": "healthy", "latency_ms": latency_ms(start), "missions_count": count}
    except Exception as exc:
        checks["database"] = {"status": "unhealthy", "latency_ms": latency_ms(start), "error": type(exc).__name__}
        overall = "degraded"

    start = time.monotonic()
    try:
        from spectra_persistence.advisory_locks import advisory_lock_owner, stable_lock_id
        from spectra_persistence.database import advisory_lock_connection

        test_lock_id = stable_lock_id("spectra_health_deep_test")
        async with advisory_lock_owner(test_lock_id, connection_factory=advisory_lock_connection) as lock_conn:
            if lock_conn is not None:
                checks["advisory_lock"] = {"status": "healthy", "latency_ms": latency_ms(start)}
            else:
                checks["advisory_lock"] = {"status": "degraded", "latency_ms": latency_ms(start), "error": "lock not acquired"}
                overall = "degraded"
    except Exception as exc:
        checks["advisory_lock"] = {"status": "unhealthy", "latency_ms": latency_ms(start), "error": type(exc).__name__}
        overall = "degraded"

    start = time.monotonic()
    try:
        from spectra_infra.cache import get_cache

        cache = get_cache()
        if cache:
            probe_key = f"health:deep:{uuid.uuid4().hex}"
            await cache.set(probe_key, "ok", ttl=10)
            val = await cache.get(probe_key)
            await cache.delete(probe_key)
            if val == "ok":
                checks["cache"] = {"status": "healthy", "latency_ms": latency_ms(start)}
            else:
                checks["cache"] = {"status": "degraded", "latency_ms": latency_ms(start), "error": "read mismatch"}
                overall = "degraded"
        else:
            checks["cache"] = {"status": "not_configured", "latency_ms": latency_ms(start)}
    except Exception as exc:
        checks["cache"] = {"status": "unhealthy", "latency_ms": latency_ms(start), "error": type(exc).__name__}
        overall = "degraded"

    task_statuses: dict[str, Any] = {}
    if scheduler_state._scheduler_instance is not None:
        task_statuses, tasks_degraded = task_health_details(scheduler_state._scheduler_instance)
        if tasks_degraded:
            overall = "degraded"

        start = time.monotonic()
        try:
            from spectra_infra.cache import get_cache

            cache = get_cache()
            if cache:
                heartbeat = await cache.get("spectra:service:scheduler:heartbeat")
                if heartbeat and isinstance(heartbeat, dict):
                    last_ts = heartbeat.get("timestamp")
                    if last_ts:
                        last_dt = datetime.fromisoformat(str(last_ts))
                        age_seconds = (datetime.now(UTC) - last_dt).total_seconds()
                        task_statuses["health_reporter"]["heartbeat_age_seconds"] = round(age_seconds, 1)
                        if age_seconds > 120:
                            task_statuses["health_reporter"]["state"] = "stale"
                            overall = "degraded"
            checks["tasks"] = {"status": "healthy" if overall == "healthy" else "degraded", "details": task_statuses}
        except Exception as exc:
            checks["tasks"] = {"status": "unhealthy", "error": type(exc).__name__, "details": task_statuses}
            overall = "degraded"
    else:
        checks["tasks"] = {"status": "not_configured", "error": "scheduler not started"}
        overall = "degraded"

    if overall != "healthy":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": overall,
        "service": "scheduler",
        "timestamp": datetime.now(UTC).isoformat(),
        "checks": checks,
    }


@app.get("/internal/metrics")
@limiter.limit(RateLimits.INTERNAL_METRICS)
async def internal_node_metrics(request: Request):
    """Return local system metrics. Service auth enforced by middleware."""
    from spectra_scaling.node_metrics import collect_node_metrics

    metrics = collect_node_metrics("scheduler")
    return metrics.to_dict()


async def _scaling_metrics_payload() -> dict:
    """Return cluster metrics in the admin API response shape."""
    from spectra_scaling.metrics_collector import MetricsCollector

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


@app.get("/internal/scaling/metrics")
async def internal_scaling_metrics():
    """Cluster metrics collected by scheduler, which owns Docker access."""
    return await _scaling_metrics_payload()


@app.get("/internal/scaling/dashboard")
async def internal_scaling_dashboard():
    """Comprehensive scaling dashboard data — cluster, services, nodes, autoscaler, alerts."""
    from spectra_common.config import get_settings as _get_settings
    from spectra_scaling.auto_scaler import AutoScaler, get_scaling_history
    from spectra_scaling.backends import DockerSwarmBackend
    from spectra_scaling.config import AutoScalerConfig
    from spectra_scaling.docker_client import get_service_task_nodes
    from spectra_scaling.image_updater import get_update_status
    from spectra_scaling.metrics_collector import MetricsCollector
    from spectra_scaling.notifiers import LogNotifier

    settings = _get_settings()
    collector = MetricsCollector()
    cluster = await collector.collect_all()
    cnm = cluster.cluster_node_metrics

    # --- Cluster summary ---
    cluster_summary = {
        "total_nodes": cnm.total_nodes if cnm else cluster.nodes_total,
        "healthy_nodes": cnm.healthy_nodes if cnm else cluster.nodes_healthy,
        "total_cpu_percent": round(cnm.avg_cpu_percent, 1) if cnm else round(cluster.system.cpu_percent, 1),
        "total_memory_percent": round(cnm.avg_memory_percent, 1) if cnm else round(cluster.system.memory_percent, 1),
        "min_disk_free_gb": round(cnm.min_disk_free_gb, 1) if cnm else round(cluster.system.disk_free_gb, 1),
    }

    # --- Per-service info with node placement ---
    services_info: dict[str, dict] = {}
    for svc_name, svc in cluster.services.items():
        svc_nodes = await get_service_task_nodes(svc_name)

        # Check update availability from image_updater cache
        update_available = False
        status = get_update_status()
        for s in status.get("services", []):
            if s.get("service") == svc_name:
                update_available = s.get("update_available", False)
                break

        services_info[svc_name] = {
            "replicas": svc.replicas,
            "desired": svc.desired_replicas,
            "healthy": svc.running_tasks,
            "cpu_percent": round(svc.cpu_percent, 2),
            "memory_mb": round(svc.memory_mb, 1),
            "update_available": update_available,
            "nodes": svc_nodes,
        }

    # --- Per-node breakdown ---
    nodes_list: list[dict] = []
    if cnm:
        # Gather which services run on which node
        node_services: dict[str, list[str]] = {}
        for svc_name, svc_data in services_info.items():
            for node_name in svc_data.get("nodes", []):
                node_services.setdefault(node_name, []).append(svc_name)

        for n in cnm.per_node:
            nodes_list.append({
                "name": n.name,
                "service_type": n.service_type,
                "cpu_percent": round(n.cpu_percent, 1),
                "memory_percent": round(n.memory_percent, 1),
                "disk_free_gb": round(n.disk_free_gb, 1),
                "services": node_services.get(n.name, []),
                "last_metrics_at": n.last_metrics_at,
            })

    # --- Autoscaler state ---
    scaler_config = AutoScalerConfig.from_settings(settings)
    scaler = AutoScaler(scaler_config, DockerSwarmBackend(), LogNotifier())
    scaler_status = scaler.get_status()
    history = get_scaling_history()

    autoscaler_info = {
        "enabled": settings.AUTOSCALE_ENABLED,
        "policies": scaler_status.get("policies", {}),
        "recent_actions": history[-20:],  # Last 20 for the dashboard
    }

    # --- Alerts ---
    alerts: list[dict] = []
    if cnm:
        for n in cnm.per_node:
            if n.memory_percent > 95:
                alerts.append({"severity": "critical", "message": f"{n.name} memory at {n.memory_percent:.1f}%", "at": n.last_metrics_at})
            elif n.memory_percent > 85:
                alerts.append({"severity": "warning", "message": f"{n.name} memory at {n.memory_percent:.1f}%", "at": n.last_metrics_at})
            if 0 < n.disk_free_gb < 5:
                alerts.append({"severity": "critical", "message": f"{n.name} disk free {n.disk_free_gb:.1f}GB", "at": n.last_metrics_at})
            elif 0 < n.disk_free_gb < 10:
                alerts.append({"severity": "warning", "message": f"{n.name} disk free {n.disk_free_gb:.1f}GB", "at": n.last_metrics_at})
    if cluster.system.cpu_percent > 90:
        alerts.append({"severity": "warning", "message": f"Local CPU at {cluster.system.cpu_percent:.1f}%", "at": cluster.timestamp.isoformat()})

    return {
        "cluster": cluster_summary,
        "services": services_info,
        "nodes": nodes_list,
        "autoscaler": autoscaler_info,
        "alerts": alerts,
    }


@app.get("/internal/updates/status")
async def internal_update_status():
    """Return service image versions and update availability."""
    from spectra_scaling.image_updater import get_update_status

    return get_update_status()


@app.post("/internal/updates/apply")
async def internal_update_apply(request_body: dict):
    """Trigger an image update for a specific service or all managed services."""
    from spectra_scaling.image_updater import MANAGED_SERVICES, check_and_update_services

    target = request_body.get("service")
    if target and target not in MANAGED_SERVICES:
        return {"success": False, "error": f"Unknown service: {target}"}

    original = None
    if target:
        import spectra_scaling.image_updater as _updater
        original = _updater.MANAGED_SERVICES
        _updater.MANAGED_SERVICES = {target}

    try:
        results = await check_and_update_services(apply=True)
    finally:
        if original is not None:
            _updater.MANAGED_SERVICES = original

    return {
        "results": [
            {"service": r.service, "old_digest": r.old_digest, "new_digest": r.new_digest,
             "success": r.success, "error": r.error}
            for r in results
        ],
    }


@app.get("/internal/updates/rollback-candidates")
async def internal_rollback_candidates():
    """Return services that have a previous version available for rollback."""
    from spectra_scaling.image_updater import get_rollback_candidates

    return {"candidates": get_rollback_candidates()}


@app.post("/internal/updates/rollback")
async def internal_rollback(request_body: dict):
    """Rollback a service using Swarm's PreviousSpec."""
    from spectra_scaling.docker_client import rollback_service
    from spectra_scaling.image_updater import MANAGED_SERVICES

    service_name = request_body.get("service", "")
    if not service_name:
        return {"success": False, "error": "Missing 'service' field"}
    if service_name not in MANAGED_SERVICES:
        return {"success": False, "error": f"Unknown service: {service_name}"}

    success = await rollback_service(service_name)
    return {"success": success, "service": service_name}


_INTERNAL_ALLOWED_SERVICES = frozenset({
    "spectra_app",
    "spectra_worker",
    "spectra_ai-svc",
    "spectra_scheduler",
    "spectra_caddy",
})


@app.post("/internal/scaling/action")
async def internal_scaling_action(request_body: dict):
    """Execute a Docker scaling command on behalf of a non-manager app replica."""
    action = request_body.get("action", "")
    service_name = request_body.get("service", "")

    if action not in ("scale_up", "scale_down", "restart"):
        return {"success": False, "action": action, "service": service_name, "error": "Invalid action"}
    from spectra_scaling.docker_client import (
        get_service,
        restart_service,
        scale_service,
    )

    if service_name not in _INTERNAL_ALLOWED_SERVICES:
        return {"success": False, "action": action, "service": service_name, "error": "Service not allowed"}

    try:
        if action in ("scale_up", "scale_down"):
            svc_info = await get_service(service_name)
            current = svc_info.desired_replicas if svc_info else 1
            new_count = current + 1 if action == "scale_up" else max(1, current - 1)
            success = await scale_service(service_name, new_count)

        elif action == "restart":
            success = await restart_service(service_name)

        else:
            success = False

    except Exception:
        logger.exception("Internal scaling action failed: %s %s", action, service_name)
        success = False

    return {"success": success, "action": action, "service": service_name}
