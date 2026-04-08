"""Service registry — central factory for all extractable services.

Reads config to decide whether each service runs in-process or via HTTP gateway.
Provides singleton access and health monitoring for all services.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


class ServiceRegistry:
    """Central registry managing lifecycle and routing of all extractable services."""

    def __init__(self) -> None:
        self._services: dict[str, Any] = {}
        self._health_cache: dict[str, dict] = {}
        self._lock = asyncio.Lock()

    # LLM gateway client removed; only sandbox and database remain

    async def get_sandbox_orchestrator(self):
        """Get sandbox orchestrator — remote if URL set, local Docker otherwise."""
        if "sandbox" not in self._services:
            async with self._lock:
                if "sandbox" not in self._services:
                    if settings.SANDBOX_ORCHESTRATOR_URL:
                        from app.services.gateway.sandbox_orchestrator import (
                            SandboxOrchestratorClient,
                        )

                        api_key = (
                            settings.SANDBOX_ORCHESTRATOR_API_KEY.get_secret_value()
                            if settings.SANDBOX_ORCHESTRATOR_API_KEY
                            else ""
                        )
                        self._services["sandbox"] = SandboxOrchestratorClient(
                            settings.SANDBOX_ORCHESTRATOR_URL,
                            timeout=settings.SANDBOX_ORCHESTRATOR_TIMEOUT,
                            api_key=api_key,
                        )
                        logger.info(
                            "Sandbox orchestrator: HTTP gateway at %s",
                            settings.SANDBOX_ORCHESTRATOR_URL,
                        )
                    else:
                        from app.services.tools.sandbox import get_sandbox_pool

                        self._services["sandbox"] = get_sandbox_pool()
                        logger.info("Sandbox orchestrator: local Docker")
        return self._services["sandbox"]

    async def health_check_all(self) -> dict[str, dict]:
        """Run health checks on all registered services."""
        results: dict[str, dict] = {}
        for name, svc in self._services.items():
            if svc is None:
                results[name] = {"status": "disabled"}
                continue
            try:
                if hasattr(svc, "health_check"):
                    result = await svc.health_check()
                    if isinstance(result, bool):
                        results[name] = {"status": "healthy" if result else "unhealthy"}
                    elif isinstance(result, dict):
                        results[name] = result
                    else:
                        results[name] = {"status": "unknown"}
                else:
                    results[name] = {"status": "no_health_check"}
            except (OSError, RuntimeError, ValueError) as e:
                results[name] = {"status": "error", "error": str(e)}
        self._health_cache = results
        return results

    def get_service_topology(self) -> dict[str, dict]:
        """Return the current service topology (what's local vs remote)."""
        topology: dict[str, dict] = {}
        configs = {
            "sandbox": {
                "url_setting": "SANDBOX_ORCHESTRATOR_URL",
                "url": settings.SANDBOX_ORCHESTRATOR_URL,
            },
            "database": {"url_setting": "DATABASE_URL", "mode": "primary"},
        }
        for name, cfg in configs.items():
            url = cfg.get("url")
            topology[name] = {
                "mode": "remote" if url else "local",
                "url": url or "in-process",
                "registered": name in self._services,
                "health": self._health_cache.get(name, {}),
            }
        # Add storage
        topology["storage"] = {
            "mode": "s3" if settings.S3_ENDPOINT_URL else "local",
            "url": settings.S3_ENDPOINT_URL or "file://data/",
            "healthy": None,  # populated by health check
        }

        # Add pool node counts (populated by async callers via get_service_topology_async)
        for stype in ("sandbox_worker", "db_replica", "storage"):
            topology[stype + "_pool"] = {
                "total_nodes": 0,
                "healthy_nodes": 0,
                "nodes": [],
            }

        return topology

    async def get_service_topology_async(self) -> dict[str, dict]:
        """Return service topology with live pool node counts."""
        topology = self.get_service_topology()
        try:
            from app.core.database import async_session_maker
            from app.services.scaling import get_pool_manager

            pool = get_pool_manager()
            async with async_session_maker() as session:
                for stype in ("sandbox_worker", "db_replica", "storage"):
                    nodes = await pool.list_nodes(session, service_type=stype)
                    topology[stype + "_pool"] = {
                        "total_nodes": len(nodes),
                        "healthy_nodes": sum(1 for n in nodes if n["health_status"] == "healthy"),
                        "nodes": nodes,
                    }
        except OSError:
            pass  # Pool not initialized yet
        return topology

    async def close_all(self) -> None:
        """Close all service connections."""
        for name, svc in self._services.items():
            if svc and hasattr(svc, "close"):
                try:
                    await svc.close()
                except (OSError, RuntimeError) as e:
                    logger.warning("Error closing %s service: %s", name, e)
        self._services.clear()

    async def invalidate(self, service_name: str) -> None:
        """Invalidate a specific service (force re-creation on next access)."""
        svc = self._services.pop(service_name, None)
        if svc and hasattr(svc, "close"):
            try:
                await svc.close()
            except OSError:
                logger.debug("Error closing invalidated %s service", service_name)


# Module-level singleton
_registry: ServiceRegistry | None = None


def get_service_registry() -> ServiceRegistry:
    global _registry
    if _registry is None:
        _registry = ServiceRegistry()
    return _registry


async def close_service_registry() -> None:
    global _registry
    if _registry:
        await _registry.close_all()
        _registry = None
