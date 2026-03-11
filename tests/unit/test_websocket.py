"""
Test WebSocket functionality.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


# =============================================================================
# Connection limit tests
# =============================================================================


class TestConnectionLimits:
    """WebSocket connection limit constants."""

    def test_global_limit_defined(self):
        assert ConnectionManager.MAX_CONNECTIONS_GLOBAL == 1000

    def test_per_user_limit_defined(self):
        assert ConnectionManager.MAX_CONNECTIONS_PER_USER == 100

    def test_per_user_less_than_global(self):
        assert ConnectionManager.MAX_CONNECTIONS_PER_USER < ConnectionManager.MAX_CONNECTIONS_GLOBAL


class TestGlobalLimitReject:
    """ConnectionManager rejects connections when global limit exceeded."""

    @pytest.mark.asyncio
    async def test_rejects_when_global_limit_reached(self):
        manager = ConnectionManager()
        for _ in range(ConnectionManager.MAX_CONNECTIONS_GLOBAL):
            manager._connections.add(MagicMock())

        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.close = AsyncMock()
        ws.query_params = {"token": "tok"}
        with patch("app.core.security.decode_token", return_value={"sub": "u1"}):
            ok = await manager.connect(ws)
        assert ok is False
        ws.close.assert_awaited_once()


class TestPerUserLimitReject:
    """ConnectionManager rejects connections when per-user limit exceeded."""

    @pytest.mark.asyncio
    async def test_rejects_when_per_user_limit_reached(self):
        manager = ConnectionManager()
        user_id = "u-limited"
        manager._user_connections[user_id] = {
            MagicMock() for _ in range(ConnectionManager.MAX_CONNECTIONS_PER_USER)
        }

        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.close = AsyncMock()
        ws.query_params = {"token": "tok"}
        with patch("app.core.security.decode_token", return_value={"sub": user_id}):
            ok = await manager.connect(ws)
        assert ok is False
        ws.close.assert_awaited_once()
