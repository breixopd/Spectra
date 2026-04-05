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
    API = "api"  # Core API + auth + pages + WebSocket
    AI = "ai"  # LLM + embeddings + RAG
    WORKER = "worker"  # Tool execution from PG queue
    SCHEDULER = "scheduler"  # Background tasks only
    TOOLS = "tools"  # Tool management (subset of API)
    ALL = "all"  # Everything (development/single-node)


# Router modules each service loads
SERVICE_ROUTERS: dict[ServiceMode, list[str]] = {
    ServiceMode.API: [
        "app.api.routers.admin",
        "app.api.routers.auth",
        "app.api.routers.billing",
        "app.api.routers.cve",
        "app.api.routers.exploits",
        "app.api.routers.export",
        "app.api.routers.findings",
        "app.api.routers.health",
        "app.api.routers.manual_helpers",
        "app.api.routers.missions",
        "app.api.routers.observability",
        "app.api.routers.pentest_sessions",
        "app.api.routers.public",
        "app.api.routers.shell",
        "app.api.routers.system",
        "app.api.routers.targets",
        "app.api.routers.tools",
        "app.api.routers.ui",
        "app.api.routers.user_settings",
        "app.api.routers.vpn",
        "app.api.routers.wordlists",
    ],
    ServiceMode.AI: [
        "app.api.routers.health",
    ],
    ServiceMode.WORKER: [
        "app.api.routers.health",
    ],
    ServiceMode.SCHEDULER: [],  # No HTTP routers, runs background loops
    ServiceMode.TOOLS: [
        "app.api.routers.health",
        "app.api.routers.tools",
    ],
    ServiceMode.ALL: [
        "app.api.routers.admin",
        "app.api.routers.auth",
        "app.api.routers.billing",
        "app.api.routers.cve",
        "app.api.routers.exploits",
        "app.api.routers.export",
        "app.api.routers.findings",
        "app.api.routers.health",
        "app.api.routers.manual_helpers",
        "app.api.routers.missions",
        "app.api.routers.observability",
        "app.api.routers.pentest_sessions",
        "app.api.routers.public",
        "app.api.routers.shell",
        "app.api.routers.system",
        "app.api.routers.targets",
        "app.api.routers.tools",
        "app.api.routers.ui",
        "app.api.routers.user_settings",
        "app.api.routers.vpn",
        "app.api.routers.wordlists",
    ],
}
