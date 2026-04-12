"""Real-time metrics collection from Docker, system, and application sources."""

import asyncio
import logging
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime

import psutil

logger = logging.getLogger(__name__)


@dataclass
class ServiceMetrics:
    """Metrics for a single Docker service."""

    name: str
    replicas: int = 0
    desired_replicas: int = 0
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    memory_limit_mb: float = 0.0
    memory_percent: float = 0.0
    healthy: bool = True
    failed_tasks: int = 0
    running_tasks: int = 0


@dataclass
class SystemMetrics:
    """Host-level system metrics."""

    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_available_mb: float = 0.0
    disk_percent: float = 0.0
    disk_free_gb: float = 0.0
    load_avg_1m: float = 0.0
    load_avg_5m: float = 0.0


@dataclass
class QueueMetrics:
    """Application queue metrics."""

    depth: int = 0
    in_progress: int = 0
    completed: int = 0
    avg_wait_secs: float = 0.0
    oldest_job_secs: float = 0.0


@dataclass
class NodeMetricsSummary:
    """Cached metrics for a single pool node."""

    name: str
    service_type: str
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    disk_free_gb: float = 0.0
    last_metrics_at: str | None = None


@dataclass
class ClusterNodeMetrics:
    """Aggregated cluster-wide metrics from pool node agents."""

    total_nodes: int = 0
    healthy_nodes: int = 0
    avg_cpu_percent: float = 0.0
    avg_memory_percent: float = 0.0
    min_disk_free_gb: float = 0.0
    per_node: list[NodeMetricsSummary] = field(default_factory=list)


@dataclass
class ClusterMetrics:
    """Aggregated cluster-wide metrics."""

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    services: dict[str, ServiceMetrics] = field(default_factory=dict)
    system: SystemMetrics = field(default_factory=SystemMetrics)
    queue: QueueMetrics = field(default_factory=QueueMetrics)
    nodes_total: int = 0
    nodes_healthy: int = 0
    nodes_unhealthy: int = 0
    cluster_node_metrics: ClusterNodeMetrics | None = None


class MetricsCollector:
    """Collects real-time metrics from Docker Swarm, system, and app sources."""

    SWARM_SERVICES = (
        "spectra_app",
        "spectra_worker",
        "spectra_ai-svc",
        "spectra_scheduler",
        "spectra_caddy",
    )

    async def collect_all(self) -> ClusterMetrics:
        """Collect all metrics concurrently."""
        metrics = ClusterMetrics()

        # Run independent collectors in parallel
        service_task = asyncio.create_task(self._collect_service_metrics())
        system_task = asyncio.create_task(self._collect_system_metrics())
        queue_task = asyncio.create_task(self._collect_queue_metrics())
        node_task = asyncio.create_task(self._collect_node_metrics())
        cluster_task = asyncio.create_task(self.collect_cluster_metrics())

        metrics.services = await service_task
        metrics.system = await system_task
        metrics.queue = await queue_task
        nodes = await node_task
        metrics.nodes_total = nodes[0]
        metrics.nodes_healthy = nodes[1]
        metrics.nodes_unhealthy = nodes[2]
        metrics.cluster_node_metrics = await cluster_task

        return metrics

    async def _collect_service_metrics(self) -> dict[str, ServiceMetrics]:
        """Collect per-service CPU/memory from Docker stats."""
        from app.services.scaling.docker_client import get_container_stats, list_services

        services: dict[str, ServiceMetrics] = {}
        try:
            # Get service replica counts and desired state
            svc_list = await list_services()
            for svc in svc_list:
                services[svc.name] = ServiceMetrics(
                    name=svc.name,
                    replicas=svc.running_tasks,
                    desired_replicas=svc.desired_replicas,
                    running_tasks=svc.running_tasks,
                    healthy=(svc.running_tasks == svc.desired_replicas),
                    failed_tasks=max(0, svc.desired_replicas - svc.running_tasks),
                )

            # Get container-level stats for CPU/memory
            container_stats = await get_container_stats()
            for cs in container_stats:
                # Extract service name from container name
                # e.g. spectra_app.1.xxx -> spectra_app
                container_name = cs.name
                service_name = (
                    container_name.rsplit(".", 2)[0]
                    if "." in container_name
                    else container_name
                )
                if service_name in services:
                    services[service_name].cpu_percent += cs.cpu_percent
                    services[service_name].memory_mb += cs.memory_mb

            # Average CPU across replicas
            for svc in services.values():
                if svc.replicas > 0:
                    svc.cpu_percent /= svc.replicas

        except Exception as exc:
            logger.warning("Failed to collect service metrics: %s", exc)

        return services

    async def _collect_system_metrics(self) -> SystemMetrics:
        """Collect host-level system metrics using psutil."""
        try:
            cpu = await asyncio.to_thread(psutil.cpu_percent, interval=1)
            mem = psutil.virtual_memory()
            disk = shutil.disk_usage("/")
            load = psutil.getloadavg()

            return SystemMetrics(
                cpu_percent=cpu,
                memory_percent=mem.percent,
                memory_available_mb=mem.available / (1024 * 1024),
                disk_percent=(disk.used / disk.total) * 100,
                disk_free_gb=disk.free / (1024**3),
                load_avg_1m=load[0],
                load_avg_5m=load[1],
            )
        except Exception as exc:
            logger.warning("Failed to collect system metrics: %s", exc)
            return SystemMetrics()

    async def _collect_queue_metrics(self) -> QueueMetrics:
        """Collect queue metrics from the application job queue."""
        try:
            from app.core.queue import queue_metrics

            raw = await queue_metrics()
            return QueueMetrics(
                depth=raw.get("depth", 0),
                in_progress=raw.get("in_progress", 0),
                completed=raw.get("completed", 0),
                avg_wait_secs=raw.get("avg_wait_seconds", 0.0),
                oldest_job_secs=raw.get("oldest_job_age_seconds", 0.0),
            )
        except Exception as exc:
            logger.warning("Failed to collect queue metrics: %s", exc)
            return QueueMetrics()

    async def _collect_node_metrics(self) -> tuple[int, int, int]:
        """Collect Swarm node health counts."""
        from app.services.scaling.docker_client import list_nodes

        total = healthy = unhealthy = 0
        try:
            nodes = await list_nodes()
            for node in nodes:
                total += 1
                if node.status.lower() == "ready":
                    healthy += 1
                else:
                    unhealthy += 1
        except Exception as exc:
            logger.warning("Failed to collect node metrics: %s", exc)
        return total, healthy, unhealthy


    async def collect_cluster_metrics(self) -> ClusterNodeMetrics:
        """Aggregate cached node metrics from PoolManager (stored in metadata_.node_metrics)."""
        result = ClusterNodeMetrics()
        try:
            from sqlalchemy import select

            from app.core.database import async_session_maker
            from app.models.server_node import ServerNode

            async with async_session_maker() as session:
                rows = (await session.execute(
                    select(ServerNode).where(ServerNode.is_active)
                )).scalars().all()

            cpu_values: list[float] = []
            mem_values: list[float] = []
            disk_values: list[float] = []

            for node in rows:
                result.total_nodes += 1
                if node.health_status == "healthy":
                    result.healthy_nodes += 1

                nm = (node.metadata_ or {}).get("node_metrics", {})
                cpu = float(nm.get("cpu_percent", 0))
                mem = float(nm.get("memory_percent", 0))
                # Find min disk free from disk list
                disks = nm.get("disks", [])
                disk_free = min(
                    (d.get("free_gb", 0) for d in disks),
                    default=0.0,
                )
                ts = nm.get("timestamp")
                last_at = None
                if ts:
                    from datetime import datetime as _dt
                    try:
                        last_at = _dt.fromtimestamp(float(ts), tz=UTC).isoformat()
                    except (ValueError, TypeError, OSError):
                        last_at = str(ts)

                summary = NodeMetricsSummary(
                    name=node.name,
                    service_type=node.service_type,
                    cpu_percent=cpu,
                    memory_percent=mem,
                    disk_free_gb=disk_free,
                    last_metrics_at=last_at,
                )
                result.per_node.append(summary)

                if nm:  # Only include nodes that have reported metrics
                    cpu_values.append(cpu)
                    mem_values.append(mem)
                    disk_values.append(disk_free)

            if cpu_values:
                result.avg_cpu_percent = sum(cpu_values) / len(cpu_values)
            if mem_values:
                result.avg_memory_percent = sum(mem_values) / len(mem_values)
            if disk_values:
                result.min_disk_free_gb = min(disk_values)

        except Exception as exc:
            logger.warning("Failed to collect cluster node metrics: %s", exc)

        return result


def _parse_mem(s: str) -> float:
    """Parse Docker memory string like '256MiB' or '1.5GiB' to MB."""
    s = s.strip().upper()
    try:
        if "GIB" in s or "GB" in s:
            return float(s.replace("GIB", "").replace("GB", "")) * 1024
        if "MIB" in s or "MB" in s:
            return float(s.replace("MIB", "").replace("MB", ""))
        if "KIB" in s or "KB" in s:
            return float(s.replace("KIB", "").replace("KB", "")) / 1024
        return float(s)
    except (ValueError, TypeError):
        return 0.0
