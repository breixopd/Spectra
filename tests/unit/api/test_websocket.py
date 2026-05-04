"""
Test WebSocket functionality.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectra_platform.mission.core.websocket import ConnectionManager

# =============================================================================
# send_personal tests
# =============================================================================


class TestSendPersonal:
    """send_personal delivers to a specific WebSocket."""

    @pytest.mark.asyncio
    async def test_send_personal_to_connected(self):
        from starlette.websockets import WebSocketState

        manager = ConnectionManager()
        ws = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED
        ws.send_text = AsyncMock()

        result = await manager.send_personal(ws, "hello")
        assert result is True
        ws.send_text.assert_awaited_once_with("hello")

    @pytest.mark.asyncio
    async def test_send_personal_to_disconnected(self):
        from starlette.websockets import WebSocketState

        manager = ConnectionManager()
        ws = AsyncMock()
        ws.client_state = WebSocketState.DISCONNECTED

        result = await manager.send_personal(ws, "hello")
        assert result is False


# =============================================================================
# Broadcast sends to all connections
# =============================================================================


class TestBroadcastAll:
    """broadcast sends message to every connected WebSocket."""

    @pytest.mark.asyncio
    async def test_broadcast_multiple_clients(self):
        from starlette.websockets import WebSocketState

        manager = ConnectionManager()
        sockets = []
        for _ in range(3):
            ws = AsyncMock()
            ws.accept = AsyncMock()
            ws.send_text = AsyncMock()
            ws.client_state = WebSocketState.CONNECTED
            await manager.connect(ws, require_auth=False)
            sockets.append(ws)

        await manager.broadcast("msg")
        for ws in sockets:
            ws.send_text.assert_awaited_once_with("msg")

    @pytest.mark.asyncio
    async def test_broadcast_skips_disconnected(self):
        from starlette.websockets import WebSocketState

        manager = ConnectionManager()
        alive = AsyncMock()
        alive.accept = AsyncMock()
        alive.send_text = AsyncMock()
        alive.client_state = WebSocketState.CONNECTED

        dead = AsyncMock()
        dead.accept = AsyncMock()
        dead.send_text = AsyncMock()
        dead.client_state = WebSocketState.DISCONNECTED

        await manager.connect(alive, require_auth=False)
        await manager.connect(dead, require_auth=False)

        await manager.broadcast("msg")
        alive.send_text.assert_awaited_once_with("msg")
        dead.send_text.assert_not_awaited()


# =============================================================================
# Disconnect removes from per-user tracking
# =============================================================================


class TestDisconnectUserTracking:
    """disconnect removes WebSocket from _user_connections."""

    @pytest.mark.asyncio
    async def test_disconnect_removes_from_user_map(self):
        manager = ConnectionManager()

        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.query_params = {"token": "tok"}
        ws.state = MagicMock()

        with patch("spectra_platform.auth.security.decode_token", return_value={"sub": "alice"}):
            await manager.connect(ws)

        assert ws in manager._user_connections.get("alice", set())

        await manager.disconnect(ws)
        assert ws not in manager._user_connections.get("alice", set())

    @pytest.mark.asyncio
    async def test_disconnect_cleans_empty_user_entry(self):
        manager = ConnectionManager()

        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.query_params = {"token": "tok"}
        ws.state = MagicMock()

        with patch("spectra_platform.auth.security.decode_token", return_value={"sub": "bob"}):
            await manager.connect(ws)

        await manager.disconnect(ws)
        assert "bob" not in manager._user_connections


# =============================================================================
# Original tests
# =============================================================================


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
        with patch("spectra_platform.auth.security.decode_token", return_value={"sub": "u1"}):
            ok = await manager.connect(ws)
        assert ok is False
        ws.close.assert_awaited_once()


class TestPerUserLimitReject:
    """ConnectionManager rejects connections when per-user limit exceeded."""

    @pytest.mark.asyncio
    async def test_rejects_when_per_user_limit_reached(self):
        manager = ConnectionManager()
        user_id = "u-limited"
        manager._user_connections[user_id] = {MagicMock() for _ in range(ConnectionManager.MAX_CONNECTIONS_PER_USER)}

        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.close = AsyncMock()
        ws.query_params = {"token": "tok"}
        with patch("spectra_platform.auth.security.decode_token", return_value={"sub": user_id}):
            ok = await manager.connect(ws)
        assert ok is False
        ws.close.assert_awaited_once()


# =============================================================================
# Shell router keepalive tests
# =============================================================================


class TestShellKeepalive:
    """Keepalive task lifecycle during shell WebSocket sessions."""

    @pytest.mark.asyncio
    async def test_keepalive_sends_ping(self):
        """_keepalive sends a JSON ping after sleeping."""
        from spectra_api.api.routers.shell import _keepalive

        mock_ws = AsyncMock()
        # Let the first sleep succeed, then raise to break the loop
        mock_ws.send_json = AsyncMock(side_effect=[None, OSError("stop")])

        with patch("spectra_api.api.routers.shell.asyncio.sleep", new_callable=AsyncMock):
            await _keepalive(mock_ws)

        mock_ws.send_json.assert_any_call({"type": "ping"})

    @pytest.mark.asyncio
    async def test_keepalive_task_created_and_cancelled(self):
        """shell_websocket creates a keepalive task and cancels it on disconnect."""

        from spectra_api.api.routers.shell import shell_websocket

        mock_ws = AsyncMock()
        mock_ws.accept = AsyncMock()
        mock_ws.receive_text = AsyncMock(
            side_effect=__import__("starlette.websockets", fromlist=["WebSocketDisconnect"]).WebSocketDisconnect()
        )
        mock_ws.send_json = AsyncMock()

        mock_session = AsyncMock()
        mock_session.mission_id = "mission-1"
        mock_session.connect_websocket = AsyncMock()
        mock_session.disconnect_websocket = AsyncMock()

        mock_user = MagicMock()
        mock_user.id = "u-1"
        mock_user.username = "tester"
        mock_user.is_superuser = False

        mock_mission = MagicMock()
        mock_mission.user_id = "u-1"

        # Track create_task calls and capture the cancel calls
        mock_task = MagicMock()
        mock_task.cancel = MagicMock()

        with (
            patch("spectra_api.api.routers.shell.validate_websocket_token", return_value=mock_user),
            patch("spectra_api.api.routers.shell.check_feature_allowed", new_callable=AsyncMock),
            patch("spectra_api.api.routers.shell.shell_manager") as mock_mgr,
            patch("spectra_api.api.routers.shell.audit_log_event", new_callable=AsyncMock),
            patch("spectra_api.api.routers.shell.async_session_maker") as mock_session_maker,
            patch("spectra_api.api.routers.shell.asyncio.create_task", return_value=mock_task) as mock_ct,
        ):
            mock_mgr.get_session = AsyncMock(return_value=mock_session)
            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_mission
            mock_db.execute = AsyncMock(return_value=mock_result)
            mock_session_maker.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_maker.return_value.__aexit__ = AsyncMock(return_value=False)

            await shell_websocket(mock_ws, "123e4567-e89b-12d3-a456-426614174000", token="valid")

            # A keepalive task was created
            assert mock_ct.called
            # The task was cancelled in the finally block
            mock_task.cancel.assert_called()
