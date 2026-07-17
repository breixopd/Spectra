"""Unit tests for resource manager capacity calculator."""

import pytest

from spectra_scaling.resource_manager import ResourceManager


class TestResourceManager:
    def test_worker_capacity_calculation(self):
        result = ResourceManager.calculate_node_capacity(total_memory_mb=4096, total_cpu_cores=4, service_type="worker")
        assert result["max_containers"] > 0
        assert result["warm_pool_size"] >= 1
        assert result["recommended_replicas"] >= 1

    def test_api_capacity_smaller_than_worker(self):
        worker = ResourceManager.calculate_node_capacity(4096, 4, "worker")
        api = ResourceManager.calculate_node_capacity(4096, 4, "api")
        assert api["max_containers"] >= worker["max_containers"]  # API uses less per container

    def test_ai_capacity_is_limited(self):
        result = ResourceManager.calculate_node_capacity(4096, 4, "ai")
        assert result["max_containers"] > 0
        assert result["memory_per_container_mb"] == 1024

    def test_unknown_service_uses_worker_profile(self):
        result = ResourceManager.calculate_node_capacity(4096, 4, "unknown")
        worker = ResourceManager.calculate_node_capacity(4096, 4, "worker")
        assert result["max_containers"] == worker["max_containers"]

    def test_reserved_resources(self):
        result = ResourceManager.calculate_node_capacity(
            total_memory_mb=1000,
            total_cpu_cores=1,
            service_type="worker",
            reserved_memory_pct=0.5,
        )
        assert result["available_memory_mb"] == 500

    @pytest.mark.asyncio
    async def test_get_node_resources(self):
        result = await ResourceManager.get_node_resources()
        assert "total_memory_mb" in result
        assert "cpu_cores" in result
        assert result["total_memory_mb"] > 0
        assert result["cpu_cores"] > 0

    @pytest.mark.asyncio
    async def test_check_network_capacity_empty(self):
        result = await ResourceManager.check_network_capacity([])
        assert result["total_capacity"] == 0
        assert result["at_capacity"] is True
