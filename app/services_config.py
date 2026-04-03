"""Service definitions for microservices deployment.

Each service runs as an independent FastAPI instance with its own
subset of routers.
"""

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python < 3.11 fallback for UI runner
    class StrEnum(str, __import__("enum").Enum):
        pass


class ServiceMode(StrEnum):
    API = "api"  # Core API + auth + pages
    AI = "ai"  # LLM + embeddings + RAG
    SCHEDULER = "scheduler"  # Background tasks only


# Router modules each service loads
SERVICE_ROUTERS: dict[ServiceMode, list[str]] = {
    ServiceMode.API: [
        "app.api.routers.auth",
        "app.api.routers.billing",
        "app.api.routers.health",
        "app.api.routers.missions",
        "app.api.routers.targets",
        "app.api.routers.findings",
        "app.api.routers.observability",
        "app.api.routers.public",
        "app.api.routers.shell",
        "app.api.routers.ui",
        "app.api.routers.user_settings",
        "app.api.routers.vpn",
        "app.api.routers.wordlists",
        "app.api.routers.webhooks",
        "app.api.routers.admin",
        "app.api.routers.system",
    ],
    ServiceMode.AI: [
        "app.api.routers.health",
    ],
    ServiceMode.SCHEDULER: [],  # No HTTP routers, runs background loops
}
