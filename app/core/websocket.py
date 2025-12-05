"""
WebSocket Connection Manager.

Handles real-time communication with the frontend.
Provides thread-safe connection management and reliable message broadcasting.
"""

import asyncio
import logging
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketState

logger = logging.getLogger("spectra.websocket")


class ConnectionManager:
    """
    Manages active WebSocket connections.

    Thread-safe implementation that handles:
    - Connection lifecycle (connect/disconnect)
    - Reliable broadcasting with error recovery
    - Dead connection cleanup
    """

    def __init__(self) -> None:
        """Initialize the connection manager."""
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    @property
    def active_connections(self) -> list[WebSocket]:
        """Get list of active connections."""
        return list(self._connections)

    async def connect(self, websocket: WebSocket) -> None:
        """
        Accept and register a new WebSocket connection.

        Args:
            websocket: The WebSocket connection to accept.
        """
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        logger.debug("WebSocket connected. Total: %d", len(self._connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        """
        Remove a WebSocket connection.

        Args:
            websocket: The WebSocket connection to remove.
        """
        async with self._lock:
            self._connections.discard(websocket)
        logger.debug("WebSocket disconnected. Total: %d", len(self._connections))

    async def broadcast(self, message: str) -> None:
        """
        Send a message to all connected clients.

        Handles disconnected clients gracefully by removing them from
        the active connections list.

        Args:
            message: The message to broadcast.
        """
        if not self._connections:
            return

        disconnected: list[WebSocket] = []

        async with self._lock:
            connections = list(self._connections)

        for connection in connections:
            try:
                # Check if connection is still open
                if connection.client_state == WebSocketState.CONNECTED:
                    await connection.send_text(message)
                else:
                    disconnected.append(connection)
            except Exception as e:
                logger.warning("Failed to send to WebSocket: %s", e)
                disconnected.append(connection)

        # Clean up disconnected clients
        if disconnected:
            async with self._lock:
                for conn in disconnected:
                    self._connections.discard(conn)
            logger.debug("Cleaned up %d disconnected clients", len(disconnected))

    async def send_personal(self, websocket: WebSocket, message: str) -> bool:
        """
        Send a message to a specific client.

        Args:
            websocket: The target WebSocket connection.
            message: The message to send.

        Returns:
            True if message was sent successfully, False otherwise.
        """
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_text(message)
                return True
        except Exception as e:
            logger.warning("Failed to send personal message: %s", e)
        return False

    async def broadcast_json(self, data: dict[str, Any]) -> None:
        """
        Broadcast a JSON message to all connected clients.

        Args:
            data: Dictionary to serialize and broadcast.
        """
        import json

        message = json.dumps(data)
        await self.broadcast(message)

    async def broadcast_event(self, event_type: str, data: Any) -> None:
        """
        Broadcast a typed event message.

        This is the preferred method for broadcasting from services.
        Standardizes message format: {"type": event_type, "data": data}

        Args:
            event_type: Event type identifier (e.g., "log", "agent_state")
            data: Event payload
        """
        import json
        from datetime import datetime
        from enum import Enum
        from uuid import UUID

        def json_serializer(obj: Any) -> Any:
            """JSON serializer for objects not serializable by default json code"""
            if isinstance(obj, (datetime, date)):
                return obj.isoformat()
            if isinstance(obj, (UUID, Enum)):
                return str(obj)
            if hasattr(obj, "dict"):  # Pydantic models (v1)
                return obj.dict()
            if hasattr(obj, "model_dump"):  # Pydantic models (v2)
                return obj.model_dump()
            raise TypeError(f"Type {type(obj)} not serializable")
            
        from datetime import date

        try:
            message = json.dumps(
                {"type": event_type, "data": data},
                default=json_serializer
            )
            await self.broadcast(message)
        except Exception as e:
            logger.error("Failed to serialize event %s: %s", event_type, e)

    def connection_count(self) -> int:
        """
        Get the number of active connections.

        Returns:
            Number of currently connected clients.
        """
        return len(self._connections)


# Global singleton instance
manager = ConnectionManager()
