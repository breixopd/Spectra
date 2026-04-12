"""Pluggable orchestrator backends for the autoscaler."""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass
class ScaleResult:
    """Outcome of a backend orchestration operation."""

    success: bool
    service: str
    action: str
    from_replicas: int = 0
    to_replicas: int = 0
    error: str = ""


class OrchestratorBackend(abc.ABC):
    """Abstract backend for container orchestration operations."""

    @abc.abstractmethod
    async def scale(self, service: str, replicas: int) -> ScaleResult: ...

    @abc.abstractmethod
    async def restart(self, service: str) -> ScaleResult: ...

    @abc.abstractmethod
    async def get_service_replicas(self, service: str) -> int: ...

    @abc.abstractmethod
    async def get_service_cpu(self, service: str) -> float: ...

    @abc.abstractmethod
    async def update_image(self, service: str, image: str) -> ScaleResult: ...


class DockerSwarmBackend(OrchestratorBackend):
    """Docker Swarm backend using the Docker SDK."""

    async def scale(self, service: str, replicas: int) -> ScaleResult:
        from app.services.scaling.docker_client import get_service, scale_service

        svc = await get_service(service)
        old = svc.desired_replicas if svc else 0
        ok = await scale_service(service, replicas)
        return ScaleResult(ok, service, "scale", old, replicas)

    async def restart(self, service: str) -> ScaleResult:
        from app.services.scaling.docker_client import restart_service

        ok = await restart_service(service)
        return ScaleResult(ok, service, "restart")

    async def get_service_replicas(self, service: str) -> int:
        from app.services.scaling.docker_client import get_service

        svc = await get_service(service)
        return svc.desired_replicas if svc else 0

    async def get_service_cpu(self, service: str) -> float:
        from app.services.scaling.docker_client import get_container_stats

        stats = await get_container_stats()
        total = sum(s.cpu_percent for s in stats if service in s.name)
        count = sum(1 for s in stats if service in s.name)
        return total / count if count else 0.0

    async def update_image(self, service: str, image: str) -> ScaleResult:
        from app.services.scaling.docker_client import update_service_image

        ok = await update_service_image(service, image)
        return ScaleResult(ok, service, "update_image")
