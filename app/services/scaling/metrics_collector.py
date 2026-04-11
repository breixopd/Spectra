"""Real-time metrics collection from Docker, system, and application sources."""

import asyncio
import logging
import shutil
import subprocess
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
class ClusterMetrics:
    """Aggregated cluster-wide metrics."""

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    services: dict[str, ServiceMetrics] = field(default_factory=dict)
    system: SystemMetrics = field(default_factory=SystemMetrics)
    queue: QueueMetrics = field(default_factory=QueueMetrics)
    nodes_total: int = 0
    nodes_healthy: int = 0
    nodes_unhealthy: int = 0


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

        metrics.services = await service_task
        metrics.system = await system_task
        metrics.queue = await queue_task
        nodes = await node_task
        metrics.nodes_total = nodes[0]
        metrics.nodes_healthy = nodes[1]
        metrics.nodes_unhealthy = nodes[2]

        return metrics

    async def _collect_service_metrics(self) -> dict[str, ServiceMetrics]:
        """Collect per-service CPU/memory from Docker stats."""
        services: dict[str, ServiceMetrics] = {}
        try:
            # Get service replica counts and desired state
            result = await asyncio.to_thread(
                subprocess.run,
                ["docker", "service", "ls", "--format", "{{.Name}} {{.Replicas}}"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if not line.strip():
                        continue
                    parts = line.split()
                    if len(parts) >= 2:
                        name = parts[0]
                        replicas_str = parts[1]  # "2/2" format
                        running, desired = 0, 0
                        if "/" in replicas_str:
                            running, desired = (int(x) for x in replicas_str.split("/"))
                        services[name] = ServiceMetrics(
                            name=name,
                            replicas=running,
                            desired_replicas=desired,
                            running_tasks=running,
                            healthy=(running == desired),
                            failed_tasks=max(0, desired - running),
                        )

            # Get container-level stats for CPU/memory
            # docker stats --no-stream gives per-container stats
            result = await asyncio.to_thread(
                subprocess.run,
                [
                    "docker",
                    "stats",
                    "--no-stream",
                    "--format",
                    "{{.Name}} {{.CPUPerc}} {{.MemUsage}}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if not line.strip():
                        continue
                    # Parse: "spectra_app.1.xxx 2.50% 256MiB / 3GiB"
                    parts = line.split()
                    if len(parts) < 4:
                        continue
                    container_name = parts[0]
                    # Extract service name from container name
                    # e.g. spectra_app.1.xxx -> spectra_app
                    service_name = (
                        container_name.rsplit(".", 2)[0]
                        if "." in container_name
                        else container_name
                    )
                    cpu_str = parts[1].rstrip("%")
                    mem_used_str = parts[2]

                    try:
                        cpu = float(cpu_str)
                    except ValueError:
                        cpu = 0.0

                    mem_mb = _parse_mem(mem_used_str)

                    if service_name in services:
                        # Accumulate across replicas
                        services[service_name].cpu_percent += cpu
                        services[service_name].memory_mb += mem_mb

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
        total = healthy = unhealthy = 0
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["docker", "node", "ls", "--format", "{{.Status}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if not line.strip():
                        continue
                    total += 1
                    if line.strip().lower() == "ready":
                        healthy += 1
                    else:
                        unhealthy += 1
        except Exception as exc:
            logger.warning("Failed to collect node metrics: %s", exc)
        return total, healthy, unhealthy


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
