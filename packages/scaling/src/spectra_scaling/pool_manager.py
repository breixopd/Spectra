"""Server pool manager — tracks, health-checks, and load-balances across server nodes."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from datetime import datetime

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_persistence.database import async_session_maker

logger = logging.getLogger(__name__)

_pool_manager: ServerPoolManager | None = None


class ServerPoolManager:
    """Manages pools of server nodes with health checks and load balancing."""

    def __init__(self) -> None:
        self._health_task: asyncio.Task | None = None
        self._health_interval = 30  # seconds
        logger.info("Server pool manager initialized")

    async def add_node(
        self,
        session: AsyncSession,
        service_type: str,
        name: str,
        url: str,
        *,
        api_key: str | None = None,
        is_primary: bool = False,
        weight: int = 1,
        max_capacity: int = 10,
        metadata: dict | None = None,
    ) -> dict:
        """Register a new server node."""
        from spectra_persistence.models.server_node import ServerNode

        node = ServerNode(
            service_type=service_type,
            name=name,
            url=url.rstrip("/"),
            is_primary=is_primary,
            weight=weight,
            max_capacity=max_capacity,
            metadata_=metadata,
        )
        node.set_api_key(api_key)
        session.add(node)
        await session.flush()
        logger.info("Added %s node: %s (%s)", service_type, name, url)

        # Auto-enable autoscale when any new host joins the pool
        await self._auto_enable_autoscale(session)

        return node.to_dict()

    async def _auto_enable_autoscale(self, session: AsyncSession) -> None:
        """Enable AUTOSCALE_ENABLED in runtime settings if not already on."""
        import spectra_common.config as config

        if config.settings.AUTOSCALE_ENABLED:
            return  # already enabled
        try:
            from spectra_system.runtime_settings import upsert_system_config_values

            await upsert_system_config_values(session, {
                "AUTOSCALE_ENABLED": ("true", False),
            })
            config.settings.AUTOSCALE_ENABLED = True
            logger.info("Auto-scaling enabled — new compute host detected")
        except Exception:
            logger.warning("Failed to auto-enable autoscale", exc_info=True)

    async def remove_node(self, session: AsyncSession, node_id: int) -> bool:
        """Remove a server node."""
        from spectra_persistence.models.server_node import ServerNode

        result = await session.execute(select(ServerNode).where(ServerNode.id == node_id))
        node = result.scalar_one_or_none()
        if node:
            logger.info("Removing %s node: %s (%s)", node.service_type, node.name, node.url)
            await session.delete(node)
            return True
        return False

    async def list_nodes(
        self, session: AsyncSession, service_type: str | None = None, active_only: bool = True
    ) -> list[dict]:
        """List server nodes, optionally filtered by service type."""
        from spectra_persistence.models.server_node import ServerNode

        query = select(ServerNode)
        if service_type:
            query = query.where(ServerNode.service_type == service_type)
        if active_only:
            query = query.where(ServerNode.is_active)
        query = query.order_by(ServerNode.is_primary.desc(), ServerNode.weight.desc())
        result = await session.execute(query)
        return [n.to_dict() for n in result.scalars().all()]

    async def get_node(self, session: AsyncSession, node_id: int) -> dict | None:
        """Get a single node by ID."""
        from spectra_persistence.models.server_node import ServerNode

        result = await session.execute(select(ServerNode).where(ServerNode.id == node_id))
        node = result.scalar_one_or_none()
        return node.to_dict() if node else None

    async def update_node(self, session: AsyncSession, node_id: int, **kwargs) -> dict | None:
        """Update node fields."""
        from spectra_persistence.models.server_node import ServerNode

        result = await session.execute(select(ServerNode).where(ServerNode.id == node_id))
        node = result.scalar_one_or_none()
        if not node:
            return None
        for key, value in kwargs.items():
            if hasattr(node, key) and key not in ("id", "created_at"):
                setattr(node, key, value)
        await session.flush()
        logger.info("Updated node %d: %s", node_id, kwargs)
        return node.to_dict()

    async def select_node(self, service_type: str) -> dict | None:
        """Select the best available node for a service type using weighted least-connections.

        Algorithm: Among healthy, active nodes with available capacity,
        pick the one with the lowest (current_load / weight) ratio.
        Ties broken randomly for distribution.
        """
        from spectra_persistence.models.server_node import ServerNode

        async with async_session_maker() as session:
            result = await session.execute(
                select(ServerNode).where(
                    and_(
                        ServerNode.service_type == service_type,
                        ServerNode.is_active,
                        ServerNode.health_status == "healthy",
                    )
                )
            )
            nodes = result.scalars().all()

        if not nodes:
            return None

        # Filter by capacity
        available = [n for n in nodes if n.current_load < n.max_capacity]
        if not available:
            # All at capacity — return least loaded anyway
            logger.warning(
                "All %d %s node(s) at capacity — routing to least loaded as fallback",
                len(nodes),
                service_type,
            )
            available = list(nodes)

        # Weighted least-connections: score = current_load / weight (lower is better)
        min_score = min(n.current_load / max(n.weight, 1) for n in available)
        best = [n for n in available if n.current_load / max(n.weight, 1) <= min_score + 0.1]
        chosen = secrets.choice(best)
        return chosen.to_dict()

    async def increment_load(self, node_id: int) -> None:
        """Increment a node's current load counter."""
        from spectra_persistence.models.server_node import ServerNode

        async with async_session_maker() as session:
            await session.execute(
                update(ServerNode).where(ServerNode.id == node_id).values(current_load=ServerNode.current_load + 1)
            )
            await session.commit()

    async def decrement_load(self, node_id: int) -> None:
        """Decrement a node's current load counter."""
        from spectra_persistence.models.server_node import ServerNode

        async with async_session_maker() as session:
            await session.execute(
                update(ServerNode)
                .where(ServerNode.id == node_id, ServerNode.current_load > 0)
                .values(current_load=ServerNode.current_load - 1)
            )
            await session.commit()

    async def health_check_node(self, node: dict) -> dict:
        """Health check a single node. Returns updated status."""
        import httpx

        url = node["url"]
        raw_metadata = node.get("metadata")
        metadata: dict[str, object] = (
            {str(key): value for key, value in raw_metadata.items()}
            if isinstance(raw_metadata, dict)
            else {}
        )
        health_path_value = metadata.get("health_path")
        health_path = health_path_value if isinstance(health_path_value, str) and health_path_value else "/health"
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{url.rstrip('/')}{health_path}")
                latency_ms = round((time.monotonic() - start) * 1000, 1)
                if resp.status_code == 200:
                    return {"health_status": "healthy", "last_error": None, "latency_ms": latency_ms}
                return {"health_status": "unhealthy", "last_error": f"HTTP {resp.status_code}", "latency_ms": latency_ms}
        except (OSError, RuntimeError, ConnectionError, TimeoutError) as e:
            latency_ms = round((time.monotonic() - start) * 1000, 1)
            return {"health_status": "unhealthy", "last_error": str(e), "latency_ms": latency_ms}

    async def _collect_node_metrics(self, node: dict) -> dict | None:
        """Fetch /internal/metrics from a node. Returns metrics dict or None on failure."""
        import httpx

        from spectra_common.config import get_settings

        settings = get_settings()
        secret = settings.SERVICE_AUTH_SECRET.get_secret_value()
        url = node["url"]
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{url}/internal/metrics",
                    headers={"X-Service-Auth": secret},
                )
                if resp.status_code == 200:
                    return resp.json()
        except (OSError, RuntimeError, ConnectionError, TimeoutError):
            logger.debug("Failed to collect metrics from %s", url)
        return None

    async def health_check_all(self) -> dict[str, list[dict]]:
        """Health check all active nodes. Returns results grouped by service type."""
        from spectra_persistence.models.server_node import ServerNode

        results: dict[str, list[dict]] = {}
        async with async_session_maker() as session:
            all_nodes = await session.execute(select(ServerNode).where(ServerNode.is_active))
            nodes = all_nodes.scalars().all()

            for node in nodes:
                check = await self.health_check_node(node.to_dict())
                node.health_status = check["health_status"]
                node.last_error = check.get("last_error")
                node.last_health_check = datetime.utcnow()

                # Collect node metrics and store in metadata
                if check["health_status"] == "healthy":
                    metrics = await self._collect_node_metrics(node.to_dict())
                    if metrics:
                        existing = node.metadata_ or {}
                        existing["node_metrics"] = metrics
                        node.metadata_ = existing
                if check.get("latency_ms") is not None:
                    existing = node.metadata_ or {}
                    existing["last_health_latency_ms"] = check["latency_ms"]
                    node.metadata_ = existing

                stype = node.service_type
                if stype not in results:
                    results[stype] = []
                results[stype].append(
                    {
                        **node.to_dict(),
                        "health_status": check["health_status"],
                        "last_error": check.get("last_error"),
                        "latency_ms": check.get("latency_ms"),
                    }
                )

            await session.commit()

        logger.info("Health check complete: %s", {k: len(v) for k, v in results.items()})
        return results

    async def register_local_node(self) -> dict:
        """Register the current machine as a pool node if not already registered."""
        import socket

        import psutil

        from spectra_persistence.models.server_node import ServerNode

        hostname = socket.gethostname()

        async with async_session_maker() as session:
            # Check if already registered
            result = await session.execute(
                select(ServerNode).where(ServerNode.name == hostname)
            )
            existing = result.scalar_one_or_none()
            if existing:
                logger.debug("Local node %s already registered (id=%s)", hostname, existing.id)
                return existing.to_dict()

            # Auto-detect specs
            total_mem = psutil.virtual_memory().total // (1024 * 1024)  # MB
            cpu_count = psutil.cpu_count()
            disk = psutil.disk_usage("/")
            disk_gb = disk.total // (1024**3)

            # Determine role from Swarm
            from spectra_scaling.docker_client import list_nodes

            nodes = await list_nodes()
            role = "manager"
            for node in nodes:
                if node.hostname == hostname:
                    role = node.role
                    break

            node = ServerNode(
                service_type="all",
                name=hostname,
                url="http://127.0.0.1:5000",
                is_active=True,
                is_primary=True,
                weight=1,
                max_capacity=cpu_count or 4,
                health_status="healthy",
                metadata_={
                    "cpu_cores": cpu_count,
                    "memory_mb": total_mem,
                    "disk_gb": disk_gb,
                    "role": role,
                    "auto_registered": True,
                },
            )
            session.add(node)
            await session.commit()
            await session.refresh(node)
            logger.info(
                "Auto-registered local node %s (role=%s, cpu=%s, mem=%sMB)",
                hostname, role, cpu_count, total_mem,
            )
            return node.to_dict()

    async def start_health_loop(self) -> None:
        """Start periodic health check loop."""

        async def _loop():
            while True:
                try:
                    await self.health_check_all()
                except (OSError, RuntimeError, ValueError):
                    logger.exception("Health check loop error")
                await asyncio.sleep(self._health_interval)

        from spectra_common.tasks import create_safe_task
        self._health_task = create_safe_task(_loop(), name="pool_health_check")
        logger.info("Health check loop started (interval=%ds)", self._health_interval)

    async def get_cluster_capacity(self) -> dict:
        """Return total CPU cores, memory MB, and per-service max replicas.

        Sums resources across all healthy nodes, reserves 20% for system
        overhead, then divides by per-replica requirements.
        """
        from spectra_persistence.models.server_node import ServerNode
        from spectra_scaling.config import DEFAULT_RESOURCE_REQUIREMENTS

        total_cpu = 0.0
        total_memory_mb = 0.0

        async with async_session_maker() as session:
            result = await session.execute(
                select(ServerNode).where(
                    and_(
                        ServerNode.is_active,
                        ServerNode.health_status == "healthy",
                    )
                )
            )
            nodes = result.scalars().all()

            for node in nodes:
                meta = node.metadata_ or {}
                node_metrics = meta.get("node_metrics", {})
                # Prefer reported metrics; fall back to capacity estimate
                cpu_cores = node_metrics.get("cpu_count", node.max_capacity)
                memory_mb = node_metrics.get("memory_total_mb", node.max_capacity * 1024)
                total_cpu += cpu_cores
                total_memory_mb += memory_mb

        # Reserve 20% for system overhead
        usable_cpu = total_cpu * 0.8
        usable_memory_mb = total_memory_mb * 0.8

        per_service: dict[str, int] = {}
        for svc_name, reqs in DEFAULT_RESOURCE_REQUIREMENTS.items():
            max_by_cpu = int(usable_cpu / reqs.cpu_cores) if reqs.cpu_cores > 0 else 999
            max_by_mem = int(usable_memory_mb / reqs.memory_mb) if reqs.memory_mb > 0 else 999
            per_service[svc_name] = min(max_by_cpu, max_by_mem)

        return {
            "total_cpu_cores": total_cpu,
            "total_memory_mb": total_memory_mb,
            "usable_cpu_cores": usable_cpu,
            "usable_memory_mb": usable_memory_mb,
            "healthy_nodes": len(nodes),
            "per_service_max_replicas": per_service,
        }

    async def stop_health_loop(self) -> None:
        """Stop periodic health check loop."""
        if self._health_task:
            self._health_task.cancel()
            self._health_task = None


def get_pool_manager() -> ServerPoolManager:
    """Get or create the singleton pool manager."""
    global _pool_manager
    if _pool_manager is None:
        _pool_manager = ServerPoolManager()
    return _pool_manager
