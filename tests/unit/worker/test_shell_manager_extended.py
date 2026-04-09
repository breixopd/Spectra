"""Extended tests for app.services.shell.session_manager module."""

import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.shell.session_manager import ShellSession, ShellSessionManager


@pytest.fixture
def manager():
    """Provide a fresh ShellSessionManager (singleton reset)."""
    ShellSessionManager._instance = None
    with patch("asyncio.get_event_loop", return_value=MagicMock()):
        mgr = ShellSessionManager()
    mgr.loop = MagicMock()
    mgr.listeners = {}
    mgr.sessions = {}
    yield mgr
    ShellSessionManager._instance = None


@pytest.fixture
def session():
    return ShellSession("sess-1", "10.0.0.1", mission_id="m-1")


class TestShellSessionInit:
    def test_defaults(self, session):
        assert session.session_id == "sess-1"
        assert session.target == "10.0.0.1"
        assert session.mission_id == "m-1"
        assert session.active is False
        assert session.socket is None
        assert session.websocket is None
        assert session.buffer == b""
        assert session.missions_survived == 0


class TestShellSessionBuffer:
    def test_buffer_accumulates_without_websocket(self, session):
        session.broadcast_output(b"hello ")
        session.broadcast_output(b"world")
        assert session.buffer == b"hello world"

    def test_empty_data_ignored(self, session):
        session.broadcast_output(b"")
        assert session.buffer == b""


class TestConnectDisconnectWebsocket:
    @pytest.mark.asyncio
    async def test_connect_sends_buffer(self):
        session = ShellSession("s1", "target")
        session.buffer = b"buffered data"
        ws = AsyncMock()
        await session.connect_websocket(ws)
        assert session.websocket is ws
        assert session.active is True
        ws.send_text.assert_awaited_once_with("buffered data")
        assert session.buffer == b""

    @pytest.mark.asyncio
    async def test_disconnect_clears_websocket(self):
        session = ShellSession("s1", "target")
        session.websocket = AsyncMock()
        await session.disconnect_websocket()
        assert session.websocket is None


class TestShellSessionWrite:
    @pytest.mark.asyncio
    async def test_write_sends_to_socket(self):
        session = ShellSession("s1", "target")
        session.socket = MagicMock()
        await session.write("ls -la\n")
        session.socket.sendall.assert_called_once_with(b"ls -la\n")

    @pytest.mark.asyncio
    async def test_write_no_socket_noop(self):
        session = ShellSession("s1", "target")
        await session.write("anything")

    @pytest.mark.asyncio
    async def test_write_socket_error_deactivates(self):
        session = ShellSession("s1", "target")
        session.active = True
        session.socket = MagicMock()
        session.socket.sendall.side_effect = OSError("broken pipe")
        await session.write("cmd")
        assert session.active is False


class TestAllocatePort:
    def test_returns_port_in_range(self, manager):
        with patch("socket.socket") as mock_sock:
            mock_sock.return_value.bind.return_value = None
            port = manager.allocate_port()
            assert manager.port_range_start <= port <= manager.port_range_end

    def test_wraps_around(self, manager):
        manager.next_port = manager.port_range_end
        with patch("socket.socket") as mock_sock:
            mock_sock.return_value.bind.return_value = None
            port = manager.allocate_port()
            assert port == manager.port_range_end
            assert manager.next_port == manager.port_range_start


class TestListSessions:
    def test_empty(self, manager):
        assert manager.list_sessions() == []

    def test_with_sessions(self, manager):
        s1 = ShellSession("s1", "t1", "m1")
        s1.active = True
        s2 = ShellSession("s2", "t2", "m2")
        manager.sessions["s1"] = s1
        manager.sessions["s2"] = s2
        result = manager.list_sessions()
        assert len(result) == 2
        ids = {r["id"] for r in result}
        assert ids == {"s1", "s2"}
        active_entry = next(r for r in result if r["id"] == "s1")
        assert active_entry["active"] is True


class TestStopSession:
    @pytest.mark.asyncio
    async def test_kill_session_closes_socket(self, manager):
        s = ShellSession("s1", "t1")
        s.socket = MagicMock()
        manager.sessions["s1"] = s
        await manager.kill_session("s1")
        s.socket.shutdown.assert_called_once_with(socket.SHUT_RDWR)
        s.socket.close.assert_called_once()
        assert "s1" not in manager.sessions

    @pytest.mark.asyncio
    async def test_kill_nonexistent_session_noop(self, manager):
        await manager.kill_session("no-such-id")


class TestNotifyMissionComplete:
    def test_no_sessions(self, manager):
        manager.notify_mission_complete("m-done")

    def test_increments_other_missions(self, manager):
        s = ShellSession("s1", "t1", "m-other")
        manager.sessions["s1"] = s
        manager.notify_mission_complete("m-done")
        assert s.missions_survived == 1

    def test_does_not_increment_own_mission(self, manager):
        s = ShellSession("s1", "t1", "m-done")
        manager.sessions["s1"] = s
        manager.notify_mission_complete("m-done")
        assert s.missions_survived == 0
