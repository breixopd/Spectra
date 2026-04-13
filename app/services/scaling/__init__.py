"""Multi-server scaling and pool management."""

from app.services.scaling.backends import (
    DockerSwarmBackend,
    OrchestratorBackend,
    ScaleResult,
)
from app.services.scaling.config import (
    DEFAULT_RESOURCE_REQUIREMENTS,
    AutoScalerConfig,
    ResourceRequirements,
    ServicePolicy,
)
from app.services.scaling.healer import DiagnosticResult, ServiceHealer
from app.services.scaling.notifiers import (
    LogNotifier,
    ScalingNotifier,
    SpectraNotifier,
)
from app.services.scaling.pool_manager import ServerPoolManager, get_pool_manager

__all__ = [
    "DEFAULT_RESOURCE_REQUIREMENTS",
    "AutoScalerConfig",
    "DiagnosticResult",
    "DockerSwarmBackend",
    "LogNotifier",
    "OrchestratorBackend",
    "ResourceRequirements",
    "ScaleResult",
    "ScalingNotifier",
    "ServerPoolManager",
    "ServiceHealer",
    "ServicePolicy",
    "SpectraNotifier",
    "get_pool_manager",
]
