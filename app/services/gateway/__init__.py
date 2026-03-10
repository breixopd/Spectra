"""Gateway package — HTTP client adapters for remote Spectra services."""

from app.services.gateway.http_client import GatewayClient
from app.services.gateway.service_registry import (
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
