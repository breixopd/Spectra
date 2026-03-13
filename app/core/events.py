"""
Event System for Spectra.

Implements a pub/sub pattern for internal event handling using blinker signals.
This decouples components and enables extensibility.

Usage:
    from app.core.events import events, MissionEvent

    # Subscribe to events
    @events.mission_started.connect
    async def on_mission_started(sender, **kwargs):
        mission_id = kwargs['mission_id']
        ...

    # Publish events
    await events.emit('mission_started', mission_id='abc123', target='192.168.1.1')
"""

import asyncio
import logging
from collections import deque
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from blinker import Signal

logger = logging.getLogger(__name__)


class EventType(StrEnum):
    """All event types in the system."""

    # Mission events
    MISSION_CREATED = "mission_created"
    MISSION_STARTED = "mission_started"
    MISSION_PHASE_CHANGED = "mission_phase_changed"
    MISSION_TASK_STARTED = "mission_task_started"
    MISSION_TASK_COMPLETED = "mission_task_completed"
    MISSION_TASK_FAILED = "mission_task_failed"
    MISSION_COMPLETED = "mission_completed"
    MISSION_FAILED = "mission_failed"
    MISSION_CANCELLED = "mission_cancelled"

    # Tool events
    TOOL_EXECUTION_STARTED = "tool_execution_started"
    TOOL_EXECUTION_COMPLETED = "tool_execution_completed"
    TOOL_EXECUTION_FAILED = "tool_execution_failed"
    TOOL_INSTALLED = "tool_installed"
    TOOL_INSTALLATION_FAILED = "tool_installation_failed"

    # Finding events
    FINDING_DISCOVERED = "finding_discovered"
    FINDING_VERIFIED = "finding_verified"
    FINDING_EXPLOITED = "finding_exploited"

    # Agent events
    AGENT_STATE_CHANGED = "agent_state_changed"
    CONSENSUS_VOTE_STARTED = "consensus_vote_started"
    CONSENSUS_VOTE_COMPLETED = "consensus_vote_completed"
    AGENT_THOUGHT = "agent_thought"

    # Security events
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"

    # Plugin events
    PLUGIN_UPDATED = "plugin_updated"

    # System events
    SERVICE_HEALTH_CHANGED = "service_health_changed"
    CIRCUIT_BREAKER_OPENED = "circuit_breaker_opened"
    CIRCUIT_BREAKER_CLOSED = "circuit_breaker_closed"


@dataclass
class Event:
    """Represents an event in the system."""

    type: EventType
    timestamp: datetime = field(default_factory=datetime.now)
    data: dict[str, Any] = field(default_factory=dict)
    source: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "type": self.type.value,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
            "source": self.source,
        }


class EventBus:
    """
    Central event bus for the application.

    Supports both sync and async handlers.
    Events are processed asynchronously to avoid blocking.
    """

    def __init__(self):
        self._max_history = 1000
        self._event_history: deque[Event] = deque(maxlen=self._max_history)
        self._handlers: dict[str, list[tuple[Callable, bool]]] = {}

    def subscribe(
        self,
        event_type: EventType | str,
        handler: Callable[..., Any | Coroutine[Any, Any, Any]],
        critical: bool = False,
    ) -> None:
        """
        Subscribe a handler to an event type.

        Args:
            event_type: The event type to subscribe to
            handler: Sync or async function to call when event fires
            critical: If True, exceptions in handler will be propagated
        """
        event_name = event_type.value if isinstance(event_type, EventType) else event_type

        if event_name not in self._handlers:
            self._handlers[event_name] = []
        self._handlers[event_name].append((handler, critical))

        logger.debug("Subscribed handler to %s", event_name)

    def unsubscribe(
        self,
        event_type: EventType | str,
        handler: Callable,
    ) -> None:
        """Unsubscribe a handler from an event type."""
        event_name = event_type.value if isinstance(event_type, EventType) else event_type

        if event_name in self._handlers:
            # Remove handler regardless of criticality
            self._handlers[event_name] = [h for h in self._handlers[event_name] if h[0] != handler]
            logger.debug("Unsubscribed handler from %s", event_name)

    async def emit(
        self,
        event_type: EventType | str,
        source: str = "unknown",
        **data: Any,
    ) -> None:
        """
        Emit an event to all subscribers.

        Args:
            event_type: The event type to emit
            source: Source component emitting the event
            **data: Event payload data
        """
        event_name = event_type.value if isinstance(event_type, EventType) else event_type

        try:
            resolved_type = EventType(event_name)
        except ValueError:
            logger.warning("Unknown event type '%s', skipping emit", event_name)
            return

        event = Event(
            type=resolved_type,
            source=source,
            data=data,
        )

        # Store in history
        self._event_history.append(event)

        # Log event
        logger.debug("Event emitted: %s from %s", event_name, source)

        # Call handlers
        handlers = self._handlers.get(event_name, [])
        for handler, critical in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error("Event handler error for %s: %s", event_name, e, exc_info=True)
                if critical:
                    raise

    def emit_sync(
        self,
        event_type: EventType | str,
        source: str = "unknown",
        **data: Any,
    ) -> None:
        """
        Emit an event synchronously (fire and forget).

        Creates an async task if there's a running event loop.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.emit(event_type, source, **data))
        except RuntimeError:
            # No running loop - skip async handlers
            event_name = event_type.value if isinstance(event_type, EventType) else event_type
            logger.debug("Sync emit (no loop): %s", event_name)

    def get_history(
        self,
        event_type: EventType | str | None = None,
        limit: int = 100,
    ) -> list[Event]:
        """Get recent events, optionally filtered by type."""
        events = list(self._event_history)

        if event_type:
            event_name = event_type.value if isinstance(event_type, EventType) else event_type
            events = [e for e in events if e.type.value == event_name]

        return events[-limit:]

    def get_stats(self) -> dict[str, Any]:
        """Get event statistics."""
        stats: dict[str, int] = {}
        for event in self._event_history:
            key = event.type.value
            stats[key] = stats.get(key, 0) + 1

        return {
            "total_events": len(self._event_history),
            "event_counts": stats,
            "registered_handlers": {k: len(v) for k, v in self._handlers.items()},
        }


# Global event bus instance
events = EventBus()


# Convenience decorators
def on_event(event_type: EventType | str):
    """Decorator to subscribe a function to an event type."""

    def decorator(func: Callable):
        events.subscribe(event_type, func)
        return func

    return decorator


# Pre-register common event types as signals for blinker compatibility
mission_started = Signal("mission_started")
mission_completed = Signal("mission_completed")
mission_failed = Signal("mission_failed")
finding_discovered = Signal("finding_discovered")
tool_executed = Signal("tool_executed")


__all__ = [
    "Event",
    "EventType",
    "EventBus",
    "events",
    "on_event",
    "mission_started",
    "mission_completed",
    "mission_failed",
    "finding_discovered",
    "tool_executed",
]
