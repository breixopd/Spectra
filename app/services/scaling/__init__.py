"""Multi-server scaling and pool management."""

from app.services.scaling.backends import DockerSwarmBackend, OrchestratorBackend, ScaleResult
from app.services.scaling.config import AutoScalerConfig, ServicePolicy
from app.services.scaling.notifiers import LogNotifier, ScalingNotifier, SpectraNotifier
from app.services.scaling.pool_manager import ServerPoolManager, get_pool_manager

__all__ = [
    "AutoScalerConfig",
    "DockerSwarmBackend",
    "LogNotifier",
    "OrchestratorBackend",
    "ScaleResult",
    "ScalingNotifier",
    "ServerPoolManager",
    "ServicePolicy",
    "SpectraNotifier",
    "get_pool_manager",
]
