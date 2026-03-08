"""
Test WebSocket functionality.
"""

import pytest
from unittest.mock import patch, AsyncMock

from app.core.websocket import ConnectionManager


@pytest.mark.asyncio
async def test_connection_manager_connect():
    """Test ConnectionManager can track connections."""
    manager = ConnectionManager()

    # Create a mock websocket
    mock_ws = AsyncMock()
    mock_ws.accept = AsyncMock()

    await manager.connect(mock_ws, require_auth=False)

    assert mock_ws in manager.active_connections
    mock_ws.accept.assert_awaited_once()


@pytest.mark.asyncio
async def test_connection_manager_disconnect():
    """Test ConnectionManager properly disconnects."""
    manager = ConnectionManager()

    mock_ws = AsyncMock()
    mock_ws.accept = AsyncMock()

    await manager.connect(mock_ws, require_auth=False)
    await manager.disconnect(mock_ws)

    assert mock_ws not in manager.active_connections


@pytest.mark.asyncio
async def test_connection_manager_broadcast():
    """Test ConnectionManager broadcasts to all clients."""
    from starlette.websockets import WebSocketState

    manager = ConnectionManager()

    # Add two mock websockets
    mock_ws1 = AsyncMock()
    mock_ws1.accept = AsyncMock()
    mock_ws1.send_text = AsyncMock()
    mock_ws1.client_state = WebSocketState.CONNECTED

    mock_ws2 = AsyncMock()
    mock_ws2.accept = AsyncMock()
    mock_ws2.send_text = AsyncMock()
    mock_ws2.client_state = WebSocketState.CONNECTED

    await manager.connect(mock_ws1, require_auth=False)
    await manager.connect(mock_ws2, require_auth=False)

    await manager.broadcast("test message")

    mock_ws1.send_text.assert_awaited_once_with("test message")
    mock_ws2.send_text.assert_awaited_once_with("test message")
