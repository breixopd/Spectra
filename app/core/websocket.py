"""
WebSocket Connection Manager.

Handles real-time communication with the frontend.
Provides thread-safe connection management and reliable message broadcasting.
"""

import asyncio
import logging
from typing import Any

from fastapi import WebSocket
from jose import JWTError
from starlette.websockets import WebSocketState

logger = logging.getLogger("spectra.websocket")


class ConnectionManager:
    """
    Manages active WebSocket connections.

    Thread-safe implementation that handles:
    - Connection lifecycle (connect/disconnect)
    - JWT authentication on connect
    - Reliable broadcasting with error recovery
    - Dead connection cleanup
    - Per-user and global connection limits
    """

    MAX_CONNECTIONS_PER_USER = 100
    MAX_CONNECTIONS_GLOBAL = 1000

    def __init__(self) -> None:
        """Initialize the connection manager."""
        self._connections: set[WebSocket] = set()
        self._rooms: dict[str, set[WebSocket]] = {}
        self._user_connections: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    @property
    def active_connections(self) -> list[WebSocket]:
        """Get list of active connections."""
        return list(self._connections)

    async def connect(self, websocket: WebSocket, require_auth: bool = True) -> bool:
        """
        Accept and register a new WebSocket connection.

        Args:
            websocket: The WebSocket connection to accept.
            require_auth: If True, require JWT token in query params.

        Returns:
            True if connection was accepted, False if rejected.
        """
        user_id: str | None = None

        if require_auth:
            token = websocket.query_params.get("token")
            if not token:
                await websocket.close(code=4001, reason="Authentication required")
                return False
            try:
                from app.core.security import decode_token
                payload = decode_token(token)
                user_id = payload.get("sub")
            except (JWTError, Exception):
                await websocket.close(code=4001, reason="Invalid or expired token")
                return False

        # Check global connection limit
        async with self._lock:
            if len(self._connections) >= self.MAX_CONNECTIONS_GLOBAL:
                await websocket.close(code=4008, reason="Global connection limit reached")
                return False

            # Check per-user connection limit
            if user_id:
                user_conns = self._user_connections.get(user_id, set())
                if len(user_conns) >= self.MAX_CONNECTIONS_PER_USER:
                    await websocket.close(code=4008, reason="Per-user connection limit reached")
                    return False

        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
            if user_id:
                if user_id not in self._user_connections:
                    self._user_connections[user_id] = set()
                self._user_connections[user_id].add(websocket)
            websocket.state.user_id = user_id  # type: ignore[attr-defined]
        logger.debug("WebSocket connected. Total: %d", len(self._connections))
        return True

    async def disconnect(self, websocket: WebSocket) -> None:
        """
        Remove a WebSocket connection.

        Args:
            websocket: The WebSocket connection to remove.
        """
        async with self._lock:
            self._connections.discard(websocket)
            user_id = getattr(getattr(websocket, "state", None), "user_id", None)
            if user_id and user_id in self._user_connections:
                self._user_connections[user_id].discard(websocket)
                if not self._user_connections[user_id]:
                    del self._user_connections[user_id]
        await self.leave_all_rooms(websocket)
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
            if hasattr(obj, "model_dump"):  # Pydantic models (v2)
                return obj.model_dump()
            if hasattr(obj, "dict"):  # Pydantic models (v1)
                return obj.dict()
            raise TypeError(f"Type {type(obj)} not serializable")

        from datetime import date

        try:
            message = json.dumps(
                {"type": event_type, "data": data}, default=json_serializer
            )
            await self.broadcast(message)
        except Exception as e:
            logger.error("Failed to serialize event %s: %s", event_type, e)

    async def join_room(self, websocket: WebSocket, room_id: str) -> None:
        """Add a client to a room for targeted broadcasting."""
        async with self._lock:
            if room_id not in self._rooms:
                self._rooms[room_id] = set()
            self._rooms[room_id].add(websocket)

    async def leave_room(self, websocket: WebSocket, room_id: str) -> None:
        """Remove a client from a room."""
        async with self._lock:
            if room_id in self._rooms:
                self._rooms[room_id].discard(websocket)
                if not self._rooms[room_id]:
                    del self._rooms[room_id]

    async def leave_all_rooms(self, websocket: WebSocket) -> None:
        """Remove a client from all rooms (called on disconnect)."""
        async with self._lock:
            empty_rooms = []
            for room_id, members in self._rooms.items():
                members.discard(websocket)
                if not members:
                    empty_rooms.append(room_id)
            for room_id in empty_rooms:
                del self._rooms[room_id]

    async def broadcast_to_room(self, room_id: str, message: str) -> None:
        """Send a message to all clients in a specific room."""
        async with self._lock:
            members = list(self._rooms.get(room_id, set()))
        dead: list[WebSocket] = []
        for ws in members:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                room = self._rooms.get(room_id)
                if room:
                    for ws in dead:
                        room.discard(ws)
                    if not room:
                        del self._rooms[room_id]

    async def broadcast_to_room_json(self, room_id: str, data: dict[str, Any]) -> None:
        """Send typed JSON to all clients in a specific room."""
        import json

        await self.broadcast_to_room(room_id, json.dumps(data))

    def connection_count(self) -> int:
        """
        Get the number of active connections.

        Returns:
            Number of currently connected clients.
        """
        return len(self._connections)


# Global singleton instance
manager = ConnectionManager()
