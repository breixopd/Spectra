"""Server pool manager — tracks, health-checks, and load-balances across server nodes."""

from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import UTC, datetime

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_maker

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
        from app.models.server_node import ServerNode

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
        import app.core.config as config

        if config.settings.AUTOSCALE_ENABLED:
            return  # already enabled
        try:
            from app.services.system.runtime_settings import upsert_system_config_values

            await upsert_system_config_values(session, {
                "AUTOSCALE_ENABLED": ("true", False),
            })
            config.settings.AUTOSCALE_ENABLED = True
            logger.info("Auto-scaling enabled — new compute host detected")
        except Exception:
            logger.warning("Failed to auto-enable autoscale", exc_info=True)

    async def remove_node(self, session: AsyncSession, node_id: int) -> bool:
        """Remove a server node."""
        from app.models.server_node import ServerNode

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
        from app.models.server_node import ServerNode

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
        from app.models.server_node import ServerNode

        result = await session.execute(select(ServerNode).where(ServerNode.id == node_id))
        node = result.scalar_one_or_none()
        return node.to_dict() if node else None

    async def update_node(self, session: AsyncSession, node_id: int, **kwargs) -> dict | None:
        """Update node fields."""
        from app.models.server_node import ServerNode

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
        from app.models.server_node import ServerNode

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
        from app.models.server_node import ServerNode

        async with async_session_maker() as session:
            await session.execute(
                update(ServerNode).where(ServerNode.id == node_id).values(current_load=ServerNode.current_load + 1)
            )
            await session.commit()

    async def decrement_load(self, node_id: int) -> None:
        """Decrement a node's current load counter."""
        from app.models.server_node import ServerNode

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
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{url}/health")
                if resp.status_code == 200:
                    return {"health_status": "healthy", "last_error": None}
                return {"health_status": "unhealthy", "last_error": f"HTTP {resp.status_code}"}
        except (OSError, RuntimeError, ConnectionError, TimeoutError) as e:
            return {"health_status": "unhealthy", "last_error": str(e)}

    async def _collect_node_metrics(self, node: dict) -> dict | None:
        """Fetch /internal/metrics from a node. Returns metrics dict or None on failure."""
        import httpx

        from app.core.config import get_settings

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
        from app.models.server_node import ServerNode

        results: dict[str, list[dict]] = {}
        async with async_session_maker() as session:
            all_nodes = await session.execute(select(ServerNode).where(ServerNode.is_active))
            nodes = all_nodes.scalars().all()

            for node in nodes:
                check = await self.health_check_node(node.to_dict())
                node.health_status = check["health_status"]
                node.last_error = check.get("last_error")
                node.last_health_check = datetime.now(UTC)

                # Collect node metrics and store in metadata
                if check["health_status"] == "healthy":
                    metrics = await self._collect_node_metrics(node.to_dict())
                    if metrics:
                        existing = node.metadata_ or {}
                        existing["node_metrics"] = metrics
                        node.metadata_ = existing

                stype = node.service_type
                if stype not in results:
                    results[stype] = []
                results[stype].append(
                    {
                        **node.to_dict(),
                        "health_status": check["health_status"],
                        "last_error": check.get("last_error"),
                    }
                )

            await session.commit()

        logger.info("Health check complete: %s", {k: len(v) for k, v in results.items()})
        return results

    async def start_health_loop(self) -> None:
        """Start periodic health check loop."""

        async def _loop():
            while True:
                try:
                    await self.health_check_all()
                except (OSError, RuntimeError, ValueError):
                    logger.exception("Health check loop error")
                await asyncio.sleep(self._health_interval)

        from app.core.tasks import create_safe_task
        self._health_task = create_safe_task(_loop(), name="pool_health_check")
        logger.info("Health check loop started (interval=%ds)", self._health_interval)

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
