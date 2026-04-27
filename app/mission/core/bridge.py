"""
Event to WebSocket Bridge.

Connects the internal EventBus to the WebSocketManager, allowing
events to be automatically broadcast to connected clients without
coupling services to the WebSocket implementation.

Event routing policy:
- Suppressed events (login, rate-limit) are never broadcast.
- User-scoped events are sent only to the owning user's connections.
- All other events (operational/system) are broadcast globally.
"""

import logging

from app.infrastructure.events import Event, EventType, events
from app.mission.core.websocket import manager as ws_manager

logger = logging.getLogger(__name__)

# Events that must NEVER be broadcast to clients (security-sensitive)
_SUPPRESSED_EVENTS: set[EventType] = {
    EventType.LOGIN_SUCCESS,
    EventType.LOGIN_FAILED,
    EventType.RATE_LIMIT_EXCEEDED,
}

# Events scoped to the user who owns the resource (extracted via event.data["user_id"])
_USER_SCOPED_EVENTS: set[EventType] = {
    EventType.MISSION_CREATED,
    EventType.MISSION_STARTED,
    EventType.MISSION_PHASE_CHANGED,
    EventType.MISSION_TASK_STARTED,
    EventType.MISSION_TASK_COMPLETED,
    EventType.MISSION_TASK_FAILED,
    EventType.MISSION_COMPLETED,
    EventType.MISSION_FAILED,
    EventType.MISSION_CANCELLED,
    EventType.TOOL_EXECUTION_STARTED,
    EventType.TOOL_EXECUTION_COMPLETED,
    EventType.TOOL_EXECUTION_FAILED,
    EventType.FINDING_DISCOVERED,
    EventType.FINDING_VERIFIED,
    EventType.FINDING_EXPLOITED,
    EventType.AGENT_STATE_CHANGED,
    EventType.AGENT_THOUGHT,
    EventType.CONSENSUS_VOTE_STARTED,
    EventType.CONSENSUS_VOTE_COMPLETED,
}


class EventWebSocketBridge:
    """
    Subscribes to EventBus events and forwards them to WebSockets.
    """

    def __init__(self):
        """Initialize the bridge but do not start listening yet."""
        self.listening = False

    def start(self) -> None:
        """Start listening for events."""
        if self.listening:
            return

        for event_type in EventType:
            if event_type in _SUPPRESSED_EVENTS:
                continue
            events.subscribe(event_type, self._handle_event)

        self.listening = True
        logger.info("EventWebSocketBridge started")

    def stop(self) -> None:
        """Stop listening for events."""
        if not self.listening:
            return

        for event_type in EventType:
            if event_type in _SUPPRESSED_EVENTS:
                continue
            events.unsubscribe(event_type, self._handle_event)

        self.listening = False
        logger.info("EventWebSocketBridge stopped")

    async def _handle_event(self, event: Event) -> None:
        """
        Handle an event from the bus and route it appropriately.
        """
        try:
            if event.type in _USER_SCOPED_EVENTS:
                user_id = event.data.get("user_id")
                if user_id:
                    await ws_manager.broadcast_to_user_event(
                        user_id=str(user_id),
                        event_type=event.type.value,
                        data=event.data,
                    )
                else:
                    logger.debug("User-scoped event %s has no user_id, dropping", event.type)
                return

            # System/operational events — broadcast globally
            await ws_manager.broadcast_event(event_type=event.type.value, data=event.data)
        except (OSError, RuntimeError, ConnectionError) as e:
            logger.error("Failed to bridge event %s to WebSocket: %s", event.type, e)
