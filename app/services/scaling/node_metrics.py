"""Lightweight node-level metrics collector.

Imported by every service mode to expose /internal/metrics.
Uses psutil for system stats and optionally Docker for container stats.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import asdict, dataclass, field

import psutil

logger = logging.getLogger(__name__)

# Prime the CPU percent sensor so the first real call returns a meaningful value.
psutil.cpu_percent(interval=None)


@dataclass
class DiskInfo:
    path: str
    total_gb: float
    used_gb: float
    free_gb: float
    percent: float


@dataclass
class NodeMetrics:
    """Point-in-time snapshot of local system resources."""

    hostname: str
    timestamp: float
    service_mode: str  # api, ai, scheduler, worker

    # CPU
    cpu_percent: float  # overall
    cpu_count: int
    load_avg_1m: float
    load_avg_5m: float
    load_avg_15m: float

    # Memory
    memory_total_mb: float
    memory_used_mb: float
    memory_available_mb: float
    memory_percent: float

    # Disk
    disks: list[DiskInfo] = field(default_factory=list)

    # Network (bytes since boot)
    net_bytes_sent: int = 0
    net_bytes_recv: int = 0

    # Process
    pid: int = 0
    process_cpu_percent: float = 0.0
    process_memory_mb: float = 0.0
    open_fds: int = 0

    # Docker (populated only if socket available)
    container_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def collect_node_metrics(service_mode: str = "unknown") -> NodeMetrics:
    """Collect a snapshot of local system metrics. Non-blocking, ~50ms."""
    hostname = os.environ.get("HOSTNAME", os.uname().nodename)

    # CPU
    cpu_percent = psutil.cpu_percent(interval=None)  # non-blocking if previously called
    cpu_count = psutil.cpu_count() or 1
    load_1, load_5, load_15 = os.getloadavg()

    # Memory
    mem = psutil.virtual_memory()

    # Disk - check /, /data, /var/lib/docker if they exist
    disks = []
    for path in ["/", "/data", "/var/lib/docker"]:
        try:
            usage = psutil.disk_usage(path)
            disks.append(DiskInfo(
                path=path,
                total_gb=round(usage.total / (1024**3), 1),
                used_gb=round(usage.used / (1024**3), 1),
                free_gb=round(usage.free / (1024**3), 1),
                percent=usage.percent,
            ))
        except (OSError, FileNotFoundError):
            pass

    # Network
    net = psutil.net_io_counters()

    # Process
    proc = psutil.Process()
    try:
        proc_cpu = proc.cpu_percent(interval=None)
        proc_mem = proc.memory_info().rss / (1024 * 1024)
        open_fds = proc.num_fds() if hasattr(proc, "num_fds") else 0
    except (psutil.Error, OSError):
        proc_cpu, proc_mem, open_fds = 0.0, 0.0, 0

    # Docker container count (if socket available)
    container_count = 0
    if os.path.exists("/var/run/docker.sock"):
        try:
            import asyncio

            from app.services.scaling.docker_client import count_running_containers

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # Already in async context — run synchronously via docker SDK
                import docker as _docker

                try:
                    client = _docker.from_env(timeout=5)
                    container_count = len(client.containers.list())
                    client.close()
                except Exception:
                    logger.debug("Failed to count Docker containers synchronously", exc_info=True)
            else:
                container_count = asyncio.run(count_running_containers())
        except Exception:
            logger.debug("Failed to count Docker containers", exc_info=True)

    return NodeMetrics(
        hostname=hostname,
        timestamp=time.time(),
        service_mode=service_mode,
        cpu_percent=cpu_percent,
        cpu_count=cpu_count,
        load_avg_1m=round(load_1, 2),
        load_avg_5m=round(load_5, 2),
        load_avg_15m=round(load_15, 2),
        memory_total_mb=round(mem.total / (1024 * 1024), 1),
        memory_used_mb=round(mem.used / (1024 * 1024), 1),
        memory_available_mb=round(mem.available / (1024 * 1024), 1),
        memory_percent=mem.percent,
        disks=disks,
        net_bytes_sent=net.bytes_sent,
        net_bytes_recv=net.bytes_recv,
        pid=os.getpid(),
        process_cpu_percent=round(proc_cpu, 1),
        process_memory_mb=round(proc_mem, 1),
        open_fds=open_fds,
        container_count=container_count,
    )
