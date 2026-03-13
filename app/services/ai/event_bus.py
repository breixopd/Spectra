"""Agent event bus for direct agent-to-agent messaging.

Provides pub/sub messaging between agents without going through the blackboard,
reducing latency for inter-agent coordination.
"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AgentMessage:
    """Message passed between agents."""
    sender: str
    topic: str
    payload: Any
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    correlation_id: str | None = None


# Type alias for async message handlers

MessageHandler = Callable[[AgentMessage], Awaitable[None]]


class AgentEventBus:
    """In-process pub/sub event bus for agent-to-agent communication.

    Agents subscribe to topics and receive messages asynchronously.
    Supports both broadcast (topic-based) and direct (agent-targeted) messaging.
    """

    def __init__(self):

        self._subscribers: dict[str, list[MessageHandler]] = defaultdict(list)
        self._direct_queues: dict[str, asyncio.Queue[AgentMessage]] = {}
        self._message_history: list[AgentMessage] = []
        self._max_history = 500

    def subscribe(self, topic: str, handler: MessageHandler):
        """Subscribe to a topic."""
        self._subscribers[topic].append(handler)
        logger.debug("Subscribed to topic '%s'", topic)

    def unsubscribe(self, topic: str, handler: MessageHandler):
        """Unsubscribe from a topic."""
        if handler in self._subscribers[topic]:
            self._subscribers[topic].remove(handler)

    async def publish(self, message: AgentMessage):
        """Publish a message to all subscribers of the topic."""
        self._message_history.append(message)
        if len(self._message_history) > self._max_history:
            self._message_history = self._message_history[-self._max_history:]

        handlers = self._subscribers.get(message.topic, [])
        if handlers:
            await asyncio.gather(
                *(h(message) for h in handlers),
                return_exceptions=True
            )
            logger.debug("Published to '%s': %d handlers", message.topic, len(handlers))

    async def send_direct(self, target_agent: str, message: AgentMessage):
        """Send a message directly to a specific agent's queue."""
        if target_agent not in self._direct_queues:
            self._direct_queues[target_agent] = asyncio.Queue(maxsize=100)
        await self._direct_queues[target_agent].put(message)

    async def receive_direct(self, agent_name: str, timeout: float = 5.0) -> AgentMessage | None:
        """Receive a direct message for a specific agent."""
        if agent_name not in self._direct_queues:
            self._direct_queues[agent_name] = asyncio.Queue(maxsize=100)
        try:
            return await asyncio.wait_for(
                self._direct_queues[agent_name].get(),
                timeout=timeout
            )
        except TimeoutError:
            return None

    def get_history(self, topic: str | None = None, limit: int = 50) -> list[AgentMessage]:
        """Get recent message history, optionally filtered by topic."""
        msgs = self._message_history
        if topic:
            msgs = [m for m in msgs if m.topic == topic]
        return msgs[-limit:]


# Singleton instance
_event_bus: AgentEventBus | None = None


def get_event_bus() -> AgentEventBus:
    """Get or create the global event bus."""
    global _event_bus
    if _event_bus is None:
        _event_bus = AgentEventBus()
    return _event_bus
