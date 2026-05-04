"""Host resource detection for autoscaling limits."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class HostResources:
    cpu_count: int
    cpu_limit: float
    memory_mb: int
    memory_limit_mb: int


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

    if quota_us is not None and period_us and period_us > 0:
        cpu_ratio = quota_us / period_us
    else:
        cpu_ratio = None

    memory_mb = memory_bytes // (1024 * 1024) if memory_bytes else None
    return memory_mb, cpu_ratio


def _detect_cgroup_v2() -> tuple[int | None, float | None]:
    memory_max = _read_cgroup_file("/sys/fs/cgroup/memory.max")
    cpu_max = _read_cgroup_file("/sys/fs/cgroup/cpu.max")

    cpu_ratio = None
    if cpu_max is not None:
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

    if memory_max is not None:
        memory_mb = memory_max // (1024 * 1024)
    else:
        memory_mb = None

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


def detect_host_resources() -> HostResources:
    """Detect host resources from cgroups, falling back to system limits."""
    in_docker = is_docker()
    logger.debug(f"Running in Docker: {in_docker}")

    memory_mb, cpu_ratio = _detect_cgroup_v2()
    if memory_mb is None and cpu_ratio is None:
        memory_mb, cpu_ratio = _detect_cgroup_v1()

    if memory_mb is None or memory_mb == 0:
        cpu_count, memory_mb = _detect_system_fallback()
        cpu_limit = float(cpu_count)
        memory_limit_mb = 0
    else:
        cpu_count, _ = _detect_system_fallback()
        if cpu_ratio is not None and cpu_ratio > 0:
            cpu_limit = min(float(cpu_count), cpu_ratio)
        else:
            cpu_limit = float(cpu_count)
        memory_limit_mb = memory_mb

    return HostResources(
        cpu_count=cpu_count,
        cpu_limit=cpu_limit,
        memory_mb=memory_mb,
        memory_limit_mb=memory_limit_mb,
    )


def derive_autoscale_limits(resources: HostResources) -> dict[str, int]:
    cpu_count = resources.cpu_count
    memory_mb = resources.memory_mb

    worker_max = min(cpu_count, memory_mb // 1500, 20)
    api_max = min(cpu_count // 2, 8)
    ai_max = min(cpu_count // 3, 6)

    worker_max = max(worker_max, 1)
    api_max = max(api_max, 1)
    ai_max = max(ai_max, 1)

    return {
        "worker_max": worker_max,
        "api_max": api_max,
        "ai_max": ai_max,
    }