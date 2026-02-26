import pytest
import socket
from unittest.mock import MagicMock, patch
from app.services.shell.session_manager import ShellSessionManager, ShellSession


@pytest.fixture
def shell_manager():
    # Reset singleton
    ShellSessionManager._instance = None
    manager = ShellSessionManager()
    # Mock loop for async methods
    manager.loop = MagicMock()
    # Ensure listeners dict is fresh
    manager.listeners = {}
    manager.sessions = {}
    return manager


@pytest.mark.asyncio
async def test_allocate_port(shell_manager):
    # Mock socket to appear free
    with patch("socket.socket") as mock_socket:
        mock_socket.return_value.bind.return_value = None
        port = shell_manager.allocate_port()
        assert port >= 4444 and port <= 4500
        assert shell_manager.next_port == port + 1


@pytest.mark.asyncio
async def test_start_listener(shell_manager):
    with patch("socket.socket") as mock_socket_cls:
        # We need to mock the socket object returned by constructor
        mock_socket = MagicMock()
        mock_socket_cls.return_value = mock_socket

        # When bind is called, it should succeed
        mock_socket.bind.return_value = None
        mock_socket.listen.return_value = None

        # Mock the accept call inside the thread target
        mock_socket.accept.return_value = (MagicMock(), ("127.0.0.1", 12345))

        # Mock threading to not actually start thread but just setup
        with patch("threading.Thread") as mock_thread:
            # We also need to mock allocate_port since start_listener calls it if port=0
            # And allocate_port also creates a socket to check availability

            # Let's force a port so allocate_port isn't called, simplifying the mock
            port = 4444

            result_port = shell_manager.start_listener(
                session_id="test-session",
                target="127.0.0.1",
                mission_id="mission-1",
                port=port,
            )

            assert result_port == 4444
            assert 4444 in shell_manager.listeners
            assert mock_thread.called


@pytest.mark.asyncio
async def test_ttl_cleanup(shell_manager):
    # Setup mock sessions
    session1 = ShellSession("s1", "t1", "m1")
    session2 = ShellSession("s2", "t2", "m2")

    # Needs a mock socket for shutdown/close calls
    session1.socket = MagicMock()
    session2.socket = MagicMock()

    # Fake active sessions
    shell_manager.sessions["s1"] = session1
    shell_manager.sessions["s2"] = session2

    # Mission m3 completes
    shell_manager.notify_mission_complete("m3")

    assert session1.missions_survived == 1
    assert session2.missions_survived == 1

    # Mission m4 completes
    shell_manager.notify_mission_complete("m4")

    assert session1.missions_survived == 2
    assert session2.missions_survived == 2

    # Verify sockets were closed
    assert session1.socket.close.called or session1.socket.shutdown.called
    assert session2.socket.close.called or session2.socket.shutdown.called


@pytest.mark.asyncio
async def test_mission_ownership_ttl(shell_manager):
    # Session belonging to mission m1
    session1 = ShellSession("s1", "t1", "m1")
    shell_manager.sessions["s1"] = session1

    # Mission m1 completes
    shell_manager.notify_mission_complete("m1")

    # TTL should NOT increment for session1 because it belongs to m1
    assert session1.missions_survived == 0

    # Mission m2 completes
    shell_manager.notify_mission_complete("m2")
    assert session1.missions_survived == 1
