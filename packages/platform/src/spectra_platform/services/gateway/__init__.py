"""Gateway package — HTTP client adapters for remote Spectra services."""

from spectra_platform.services.gateway.http_client import GatewayClient
from spectra_platform.services.gateway.service_registry import (
    ServiceRegistry,
    close_service_registry,
    get_service_registry,
)

__all__ = [
    "GatewayClient",
    "ServiceRegistry",
    "close_service_registry",
    "get_service_registry",
]
