"""
Protocol Interfaces for Spectra.

Defines abstract interfaces using typing.Protocol for duck-typed components.
These protocols enable type checking without requiring inheritance.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Broadcastable(Protocol):
    """Interface for components that can broadcast messages."""

    def _broadcast(self, msg_type: str, data: Any) -> None:
        """Broadcast a message to connected clients."""
        ...


@runtime_checkable
class Loggable(Protocol):
    """Interface for components with logging capability."""

    def log(self, message: str) -> None:
        """Log a message."""
        ...


@runtime_checkable
class Serializable(Protocol):
    """Interface for components that can be serialized to dict."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        ...


@runtime_checkable
class Executable(Protocol):
    """Interface for executable agents/services."""

    async def execute(self, context: Any, input_data: Any) -> Any:
        """Execute the component."""
        ...


@runtime_checkable
class Configurable(Protocol):
    """Interface for configurable components."""

    def get_config(self) -> dict[str, Any]:
        """Get current configuration."""
        ...

    def set_config(self, config: dict[str, Any]) -> None:
        """Update configuration."""
        ...


@runtime_checkable
class HealthCheckable(Protocol):
    """Interface for components with health check capability."""

    async def health_check(self) -> bool:
        """Check if component is healthy."""
        ...


@runtime_checkable
class Closeable(Protocol):
    """Interface for components that need cleanup."""

    async def close(self) -> None:
        """Clean up resources."""
        ...


class AgentInput(Protocol):
    """Base protocol for agent input types."""

    pass


class AgentOutput(Protocol):
    """Base protocol for agent output types."""

    confidence: float
    reasoning: str


@runtime_checkable
class CacheBackend(Protocol):
    """Interface for cache backends."""

    async def get(self, key: str) -> Any | None:
        """Get a value from cache."""
        ...

    async def set(self, key: str, value: Any, ttl: int) -> bool:
        """Set a value in cache."""
        ...

    async def delete(self, key: str) -> bool:
        """Delete a key from cache."""
        ...


@runtime_checkable
class EventHandler(Protocol):
    """Interface for event handlers."""

    async def handle(self, event: Any) -> None:
        """Handle an event."""
        ...


@runtime_checkable
class ToolAdapter(Protocol):
    """Interface for tool adapters."""

    async def execute(self, request: Any, output_dir: str | None = None) -> Any:
        """Execute the tool."""
        ...

    def build_command(self, request: Any, output_dir: str | None = None) -> str:
        """Build the command string."""
        ...


# ---------------------------------------------------------------------------
# Service protocols — interfaces for services that may be extracted to
# separate microservices in the future.
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMServiceProtocol(Protocol):
    """Interface for LLM inference — in-process or remote gateway."""

    async def generate(
        self,
        prompt: str,
        *,
        task_type: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
    ) -> dict: ...

    async def generate_structured(self, prompt: str, schema: dict, **kwargs: Any) -> dict: ...

    async def health_check(self) -> dict: ...

    @property
    def provider_name(self) -> str: ...


@runtime_checkable
class EmbeddingServiceProtocol(Protocol):
    """Interface for embedding generation — local, API, or remote service."""

    async def embed(self, text: str) -> list[float]: ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def dimension(self) -> int: ...

    @property
    def is_functional(self) -> bool: ...


@runtime_checkable
class RAGServiceProtocol(Protocol):
    """Interface for RAG operations — local PG or remote service."""

    async def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        min_score: float = 0.5,
    ) -> list[dict]: ...

    async def index_document(self, content: str, metadata: dict) -> str: ...

    async def delete_document(self, doc_id: str) -> bool: ...

    @property
    def is_functional(self) -> bool: ...


@runtime_checkable
class SandboxServiceProtocol(Protocol):
    """Interface for sandbox operations — local Docker or remote orchestrator."""

    async def create(
        self,
        mission_id: str,
        *,
        resource_tier: str = "medium",
        user_id: str | None = None,
    ) -> dict: ...

    async def destroy(self, mission_id: str) -> None: ...

    async def get(self, mission_id: str) -> dict | None: ...

    async def health_check(self) -> dict: ...

    @property
    def available(self) -> bool: ...


@runtime_checkable
class NotificationServiceProtocol(Protocol):
    """Interface for notifications — email, webhook, Slack, etc."""

    async def send(
        self,
        recipient: str,
        subject: str,
        body: str,
        *,
        channel: str = "email",
    ) -> bool: ...

    async def send_template(
        self,
        recipient: str,
        template_name: str,
        context: dict,
    ) -> bool: ...


__all__ = [
    "Broadcastable",
    "Loggable",
    "Serializable",
    "Executable",
    "Configurable",
    "HealthCheckable",
    "Closeable",
    "AgentInput",
    "AgentOutput",
    "CacheBackend",
    "EventHandler",
    "ToolAdapter",
    "LLMServiceProtocol",
    "EmbeddingServiceProtocol",
    "RAGServiceProtocol",
    "SandboxServiceProtocol",
    "NotificationServiceProtocol",
]
