"""Automatic resource calculation and scaling recommendations."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Resource requirements per container type
RESOURCE_PROFILES: dict[str, dict[str, float]] = {
    "worker": {"memory_mb": 512, "cpu_cores": 0.5},
    "api": {"memory_mb": 256, "cpu_cores": 0.25},
    "ai": {"memory_mb": 1024, "cpu_cores": 1.0},
    "scheduler": {"memory_mb": 128, "cpu_cores": 0.1},
}


class ResourceManager:
    """Automatic resource calculation and scaling recommendations."""

    @staticmethod
    def calculate_node_capacity(
        total_memory_mb: int,
        total_cpu_cores: int,
        service_type: str,
        reserved_memory_pct: float = 0.2,
        reserved_cpu_pct: float = 0.2,
    ) -> dict[str, Any]:
        """Calculate how many containers a node can run."""
        profile = RESOURCE_PROFILES.get(service_type, RESOURCE_PROFILES["worker"])

        available_memory = total_memory_mb * (1 - reserved_memory_pct)
        available_cpu = total_cpu_cores * (1 - reserved_cpu_pct)

        max_by_memory = int(available_memory / profile["memory_mb"]) if profile["memory_mb"] else 0
        max_by_cpu = int(available_cpu / profile["cpu_cores"]) if profile["cpu_cores"] else 0
        max_containers = min(max_by_memory, max_by_cpu)

        # Warm pool = 20% of max, minimum 1
        warm_pool = max(1, int(max_containers * 0.2))

        return {
            "max_containers": max_containers,
            "warm_pool_size": warm_pool,
            "recommended_replicas": max(1, max_containers - warm_pool),
            "memory_per_container_mb": profile["memory_mb"],
            "cpu_per_container": profile["cpu_cores"],
            "available_memory_mb": int(available_memory),
            "available_cpu_cores": round(available_cpu, 1),
        }

    @staticmethod
    async def get_node_resources() -> dict[str, Any]:
        """Get current node's resources from /proc."""
        total_memory_mb = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1024 * 1024)
        cpu_cores = os.cpu_count() or 1
        return {"total_memory_mb": total_memory_mb, "cpu_cores": cpu_cores}

    @staticmethod
    async def check_network_capacity(nodes: list) -> dict[str, Any]:
        """Check capacity across all nodes, alert if no more capacity."""
        total_capacity = 0
        total_used = 0
        capacity_warnings: list[dict[str, Any]] = []

        for node in nodes:
            capacity = ResourceManager.calculate_node_capacity(
                node.max_capacity * RESOURCE_PROFILES.get(node.service_type, RESOURCE_PROFILES["worker"])["memory_mb"],
                node.max_capacity * RESOURCE_PROFILES.get(node.service_type, RESOURCE_PROFILES["worker"])["cpu_cores"],
                node.service_type,
            )
            total_capacity += capacity["max_containers"]
            total_used += node.current_load

            utilization = node.current_load / max(1, capacity["max_containers"])
            if utilization > 0.9:
                capacity_warnings.append(
                    {
                        "node": node.name,
                        "utilization_pct": round(utilization * 100, 1),
                        "remaining": capacity["max_containers"] - node.current_load,
                    }
                )

        return {
            "total_capacity": total_capacity,
            "total_used": total_used,
            "utilization_pct": round(total_used / max(1, total_capacity) * 100, 1),
            "at_capacity": total_used >= total_capacity,
            "warnings": capacity_warnings,
        }
