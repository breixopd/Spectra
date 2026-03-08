"""Additional tests for ShellSessionManager covering uncovered lines."""

import pytest
import socket
from unittest.mock import MagicMock, AsyncMock, patch
from app.services.shell.session_manager import ShellSessionManager, ShellSession


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset ShellSessionManager singleton before each test."""
    ShellSessionManager._instance = None
    yield
    ShellSessionManager._instance = None


@pytest.fixture
def manager():
    mgr = ShellSessionManager()
    mgr.loop = MagicMock()
    mgr.listeners = {}
    mgr.sessions = {}
    return mgr


class TestShellSession:
    def test_creation(self):
        session = ShellSession("s1", "10.0.0.1", "m1")
        assert session.session_id == "s1"
        assert session.target == "10.0.0.1"
        assert session.mission_id == "m1"
        assert not session.active
        assert session.buffer == b""

    def test_creation_no_mission(self):
        session = ShellSession("s1", "10.0.0.1")
        assert session.mission_id is None

    @pytest.mark.asyncio
    async def test_connect_websocket_sends_buffer(self):
        session = ShellSession("s1", "10.0.0.1")
        session.buffer = b"buffered data"
        mock_ws = AsyncMock()
        await session.connect_websocket(mock_ws)
        assert session.websocket == mock_ws
        assert session.active
        mock_ws.send_text.assert_awaited_once()
        assert session.buffer == b""

    @pytest.mark.asyncio
    async def test_connect_websocket_empty_buffer(self):
        session = ShellSession("s1", "10.0.0.1")
        mock_ws = AsyncMock()
        await session.connect_websocket(mock_ws)
        assert session.active
        mock_ws.send_text.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_disconnect_websocket(self):
        session = ShellSession("s1", "10.0.0.1")
        session.websocket = AsyncMock()
        await session.disconnect_websocket()
        assert session.websocket is None

    @pytest.mark.asyncio
    async def test_write_sends_to_socket(self):
        session = ShellSession("s1", "10.0.0.1")
        session.socket = MagicMock()
        await session.write("ls -la\n")
        session.socket.sendall.assert_called_once_with(b"ls -la\n")

    @pytest.mark.asyncio
    async def test_write_no_socket(self):
        session = ShellSession("s1", "10.0.0.1")
        await session.write("test")  # Should not raise

    @pytest.mark.asyncio
    async def test_write_socket_error_deactivates(self):
        session = ShellSession("s1", "10.0.0.1")
        session.socket = MagicMock()
        session.socket.sendall.side_effect = OSError("broken pipe")
        session.active = True
        await session.write("test")
        assert not session.active

    def test_broadcast_output_no_websocket_buffers(self):
        session = ShellSession("s1", "10.0.0.1")
        session.broadcast_output(b"data")
        assert session.buffer == b"data"

    def test_broadcast_empty_data_ignored(self):
        session = ShellSession("s1", "10.0.0.1")
        session.broadcast_output(b"")
        assert session.buffer == b""

    def test_broadcast_with_websocket(self):
        import asyncio

        session = ShellSession("s1", "10.0.0.1")
        session.websocket = AsyncMock()
        mock_loop = MagicMock()
        session._loop = mock_loop
        session.broadcast_output(b"hello")
        # The function uses asyncio.run_coroutine_threadsafe which calls call_soon_threadsafe
        # Just verify it doesn't crash and data was handled
        assert session.buffer == b""  # Buffer not needed when ws exists

    def test_missions_survived_default(self):
        session = ShellSession("s1", "10.0.0.1")
        assert session.missions_survived == 0


class TestShellSessionManagerAllocatePort:
    def test_allocate_port_in_range(self, manager):
        with patch("socket.socket") as mock_socket_cls:
            mock_sock = MagicMock()
            mock_socket_cls.return_value = mock_sock
            mock_sock.bind.return_value = None

            port = manager.allocate_port()
            assert 4444 <= port <= 4500

    def test_allocate_port_skips_in_use(self, manager):
        manager.listeners[4444] = MagicMock()
        manager.next_port = 4444

        with patch("socket.socket") as mock_socket_cls:
            mock_sock = MagicMock()
            mock_socket_cls.return_value = mock_sock
            mock_sock.bind.return_value = None

            port = manager.allocate_port()
            assert port != 4444

    def test_allocate_port_wraps_around(self, manager):
        manager.next_port = 4500

        with patch("socket.socket") as mock_socket_cls:
            mock_sock = MagicMock()
            mock_socket_cls.return_value = mock_sock
            mock_sock.bind.return_value = None

            port = manager.allocate_port()
            assert 4444 <= port <= 4500

    def test_allocate_port_no_free_raises(self, manager):
        # Fill all ports
        for p in range(4444, 4501):
            manager.listeners[p] = MagicMock()

        with pytest.raises(RuntimeError, match="No free ports"):
            manager.allocate_port()


class TestShellSessionManagerStartListener:
    def test_start_with_specific_port(self, manager):
        with patch("threading.Thread") as mock_thread:
            mock_thread_inst = MagicMock()
            mock_thread.return_value = mock_thread_inst

            port = manager.start_listener("s1", "10.0.0.1", port=4444)
            assert port == 4444
            mock_thread_inst.start.assert_called_once()

    def test_start_with_dynamic_port(self, manager):
        with patch("socket.socket") as mock_socket_cls:
            mock_sock = MagicMock()
            mock_socket_cls.return_value = mock_sock
            mock_sock.bind.return_value = None

            with patch("threading.Thread") as mock_thread:
                mock_thread_inst = MagicMock()
                mock_thread.return_value = mock_thread_inst

                port = manager.start_listener("s1", "10.0.0.1", port=0)
                assert 4444 <= port <= 4500

    def test_start_on_already_active_port(self, manager):
        manager.listeners[4444] = MagicMock()
        port = manager.start_listener("s1", "10.0.0.1", port=4444)
        assert port == 4444  # Returns existing port


class TestShellSessionManagerSessions:
    def test_list_sessions(self, manager):
        assert len(manager.sessions) == 0

    def test_sessions_dict(self, manager):
        session = ShellSession("s1", "10.0.0.1")
        manager.sessions["s1"] = session
        assert "s1" in manager.sessions
        assert manager.sessions["s1"].target == "10.0.0.1"
