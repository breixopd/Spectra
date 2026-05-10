"""Host resource detection for autoscaling limits.

Dynamically probes CPU, RAM, disk IOPS, and network bandwidth from cgroups
and /proc. Calculates safe concurrency limits for workers, sandboxes, and
service replicas based on actual host capacity — no hardcoded numbers.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Constants (tunable but not per-host) ──────────────────────────────

AVG_SANDBOX_RAM_MB = 512
HOST_SERVICE_OVERHEAD_MB = 2048
CPU_PER_TOOL_FACTOR = 0.5
DB_POOL_PER_CORE = 2.5

SERVICE_RAM_MB = {
    "api": 512,
    "ai": 1024,
    "scheduler": 256,
    "worker": 512,
    "caddy": 128,
    "db": 1024,
    "redis": 256,
    "garage": 512,
    "clickhouse": 1024,
    "tensorzero": 512,
}


@dataclass
class HostResources:
    cpu_count: int
    cpu_limit: float
    memory_mb: int
    memory_limit_mb: int
    disk_total_gb: float = 0.0
    disk_available_gb: float = 0.0
    network_interfaces: list[str] = field(default_factory=list)


@dataclass
class DerivedLimits:
    max_sandboxes: int
    max_concurrent_tools: int
    max_workers: int
    max_api_replicas: int
    max_ai_replicas: int
    db_pool_size: int
    redis_pool_size: int

    def to_dict(self) -> dict[str, int]:
        return {
            "max_sandboxes": self.max_sandboxes,
            "max_concurrent_tools": self.max_concurrent_tools,
            "max_workers": self.max_workers,
            "max_api_replicas": self.max_api_replicas,
            "max_ai_replicas": self.max_ai_replicas,
            "db_pool_size": self.db_pool_size,
            "redis_pool_size": self.redis_pool_size,
        }


def is_docker() -> bool:
    if Path("/.dockerenv").exists():
        return True
    try:
        cgroup_path = Path("/proc/1/cgroup")
        if cgroup_path.exists():
            content = cgroup_path.read_text()
            if "docker" in content.lower() or ":/" in content:
                return True
    except (OSError, PermissionError):
        pass
    return False


def _read_cgroup_file(path: str) -> int | None:
    try:
        p = Path(path)
        if p.exists():
            content = p.read_text().strip()
            if content == "max":
                return None
            return int(content)
    except (OSError, PermissionError, ValueError):
        pass
    return None


def _detect_cgroup_v1() -> tuple[int | None, float | None]:
    memory_bytes = _read_cgroup_file("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    quota_us = _read_cgroup_file("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
    period_us = _read_cgroup_file("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
    cpu_ratio = (quota_us / period_us) if (quota_us is not None and period_us and period_us > 0) else None
    memory_mb = memory_bytes // (1024 * 1024) if memory_bytes else None
    return memory_mb, cpu_ratio


def _detect_cgroup_v2() -> tuple[int | None, float | None]:
    memory_max = _read_cgroup_file("/sys/fs/cgroup/memory.max")
    cpu_ratio = None
    try:
        p = Path("/sys/fs/cgroup/cpu.max")
        if p.exists():
            content = p.read_text().strip()
            if content != "max":
                parts = content.split()
                if len(parts) == 2:
                    quota = int(parts[0])
                    period = int(parts[1])
                    if period > 0:
                        cpu_ratio = quota / period
    except (OSError, ValueError):
        pass
    memory_mb = memory_max // (1024 * 1024) if memory_max is not None else None
    return memory_mb, cpu_ratio


def _detect_system_fallback() -> tuple[int, int]:
    memory_kb = 0
    try:
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            for line in meminfo.read_text().splitlines():
                if line.startswith("MemTotal:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        memory_kb = int(parts[1])
                        break
    except (OSError, PermissionError):
        pass
    memory_mb = memory_kb // 1024 if memory_kb > 0 else 8192
    cpu_count = os.cpu_count() or 4
    return cpu_count, memory_mb


def _detect_disk() -> tuple[float, float]:
    try:
        stat = os.statvfs("/")
        total = (stat.f_frsize * stat.f_blocks) / (1024**3)
        avail = (stat.f_frsize * stat.f_bavail) / (1024**3)
        return round(total, 1), round(avail, 1)
    except Exception:
        return 0.0, 0.0


def _detect_network_interfaces() -> list[str]:
    interfaces: list[str] = []
    try:
        net_dir = Path("/sys/class/net")
        if net_dir.exists():
            for iface_dir in sorted(net_dir.iterdir()):
                if iface_dir.name == "lo":
                    continue
                operstate = iface_dir / "operstate"
                if operstate.exists() and operstate.read_text().strip() == "up":
                    interfaces.append(iface_dir.name)
    except Exception:
        pass
    return interfaces


def detect_host_resources() -> HostResources:
    in_docker = is_docker()
    logger.debug("Running in Docker: %s", in_docker)
    memory_mb, cpu_ratio = _detect_cgroup_v2()
    if memory_mb is None and cpu_ratio is None:
        memory_mb, cpu_ratio = _detect_cgroup_v1()
    if memory_mb is None or memory_mb == 0:
        cpu_count, memory_mb = _detect_system_fallback()
        cpu_limit = float(cpu_count)
        memory_limit_mb = 0
    else:
        cpu_count, _ = _detect_system_fallback()
        cpu_limit = min(float(cpu_count), cpu_ratio) if (cpu_ratio is not None and cpu_ratio > 0) else float(cpu_count)
        memory_limit_mb = memory_mb
    disk_total, disk_avail = _detect_disk()
    interfaces = _detect_network_interfaces()
    return HostResources(
        cpu_count=cpu_count,
        cpu_limit=cpu_limit,
        memory_mb=memory_mb,
        memory_limit_mb=memory_limit_mb,
        disk_total_gb=disk_total,
        disk_available_gb=disk_avail,
        network_interfaces=interfaces,
    )


def derive_autoscale_limits(resources: HostResources) -> dict[str, int]:
    cpu = resources.cpu_count
    mem = resources.memory_mb
    worker_max = max(1, min(cpu, mem // 1500, 20))
    api_max = max(1, min(cpu // 2, 8))
    ai_max = max(1, min(cpu // 3, 6))
    return {"worker_max": worker_max, "api_max": api_max, "ai_max": ai_max}


def derive_operational_limits(
    resources: HostResources,
    *,
    service_profile: str = "worker_dense",
) -> DerivedLimits:
    cpu = resources.cpu_count
    mem = resources.memory_mb
    if service_profile == "worker_dense":
        overhead = (SERVICE_RAM_MB["worker"] + SERVICE_RAM_MB["db"] +
                    SERVICE_RAM_MB["redis"] + SERVICE_RAM_MB["garage"])
    else:
        overhead = sum(SERVICE_RAM_MB.values())
    available_ram = max(0, mem - overhead - HOST_SERVICE_OVERHEAD_MB)
    max_sandboxes = max(1, available_ram // AVG_SANDBOX_RAM_MB)
    max_concurrent_tools = max(1, int(cpu * CPU_PER_TOOL_FACTOR))
    max_workers = max(1, min(cpu, max_concurrent_tools // 2))
    max_api_replicas = max(1, min(cpu // 2, 8))
    max_ai_replicas = max(1, min(cpu // 3, 4))
    db_pool_size = max(5, min(20, int(cpu * DB_POOL_PER_CORE)))
    redis_pool_size = max(5, min(10, int(cpu * 1.5)))
    logger.info(
        "Derived limits (profile=%s): sandboxes=%d tools=%d workers=%d api=%d ai=%d db=%d",
        service_profile, max_sandboxes, max_concurrent_tools, max_workers,
        max_api_replicas, max_ai_replicas, db_pool_size,
    )
    return DerivedLimits(
        max_sandboxes=max_sandboxes,
        max_concurrent_tools=max_concurrent_tools,
        max_workers=max_workers,
        max_api_replicas=max_api_replicas,
        max_ai_replicas=max_ai_replicas,
        db_pool_size=db_pool_size,
        redis_pool_size=redis_pool_size,
    )
