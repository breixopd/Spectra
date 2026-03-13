"""
Event to WebSocket Bridge.

Connects the internal EventBus to the WebSocketManager, allowing
events to be automatically broadcast to connected clients without
coupling services to the WebSocket implementation.
"""

import logging

from app.core.events import Event, EventType, events
from app.core.websocket import manager as ws_manager

logger = logging.getLogger(__name__)


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

        # Subscribe to all event types that should be broadcast
        # We can iterate over EventType enum or subscribe to specific ones
        # Subscribe to 'mission_*', 'tool_*', 'finding_*', 'agent_*'

        # We'll use a catch-all approach by subscribing to common prefixes if logic allows,
        # but EventBus requires specific event types.

        # Subscribe to all EventType members
        for event_type in EventType:
            # We don't broadcast sensitive events or internal-only ones if needed
            # Broadcast monitoring events
            events.subscribe(event_type, self._handle_event)

        self.listening = True
        logger.info("EventWebSocketBridge started")

    def stop(self) -> None:
        """Stop listening for events."""
        if not self.listening:
            return

        for event_type in EventType:
            events.unsubscribe(event_type, self._handle_event)

        self.listening = False
        logger.info("EventWebSocketBridge stopped")

    async def _handle_event(self, event: Event) -> None:
        """
        Handle an event from the bus and broadcast it.
        """
        try:
            # Broadcast using the standard format: {type: event_type, data: ...}
            # We use event.type.value for the string representation
            await ws_manager.broadcast_event(event_type=event.type.value, data=event.data)
        except Exception as e:
            logger.error("Failed to bridge event %s to WebSocket: %s", event.type, e)
