"""
Shell Session Manager.

Manages active reverse shell connections and bridges them to WebSockets.
"""

import asyncio
import logging
import socket
import threading

from fastapi import WebSocket

from app.core.constants import SHELL_SOCKET_RECV_BYTES

logger = logging.getLogger("spectra.shell.manager")


class ShellSession:
    """Represents an active shell session."""

    def __init__(self, session_id: str, target: str, mission_id: str = None):
        self.session_id = session_id
        self.target = target
        self.mission_id = mission_id
        self.missions_survived = 0
        self.socket: socket.socket | None = None
        self.websocket: WebSocket | None = None
        self.active = False
        self.buffer = b""
        self._loop = None  # Reference to main event loop

    async def connect_websocket(self, websocket: WebSocket):
        """Connect a WebSocket to this shell session."""
        self.websocket = websocket
        self.active = True
        # Send buffered output
        if self.buffer:
            await websocket.send_text(self.buffer.decode("utf-8", errors="replace"))
            self.buffer = b""

    async def disconnect_websocket(self):
        """Disconnect the WebSocket."""
        self.websocket = None
        # Don't kill the shell session, just the UI connection

    async def write(self, data: str):
        """Write data to the shell socket."""
        if self.socket:
            try:
                self.socket.sendall(data.encode())
            except Exception as e:
                logger.error("Failed to write to shell socket: %s", e)
                self.active = False

    def broadcast_output(self, data: bytes):
        """Broadcast output to websocket if connected."""
        if not data:
            return

        if self.websocket and self._loop:
            try:
                text = data.decode("utf-8", errors="replace")
                asyncio.run_coroutine_threadsafe(self.websocket.send_text(text), self._loop)
            except Exception as e:
                logger.error("Failed to broadcast output: %s", e)
        else:
            # Buffer if no listener
            self.buffer += data


class ShellSessionManager:
    """Singleton manager for shell sessions."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.sessions = {}  # type: ignore
            cls._instance.listeners = {}  # type: ignore
            cls._instance.loop = None  # Set lazily via asyncio.get_running_loop()
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self.sessions: dict[str, ShellSession] = {}
        self.listeners: dict[int, socket.socket] = {}

        # Range for dynamic port allocation
        self.port_range_start = 4444
        self.port_range_end = 4500
        self.next_port = self.port_range_start

    def allocate_port(self) -> int:
        """Find a free port in the range."""
        start = self.next_port
        while True:
            port = self.next_port
            self.next_port += 1
            if self.next_port > self.port_range_end:
                self.next_port = self.port_range_start

            # Check if port is in use by us
            if port in self.listeners:
                if self.next_port == start:
                    raise RuntimeError("No free ports available for shell listeners")
                continue

            # Check if port is actually free on system
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.bind(("0.0.0.0", port))
                sock.close()
                return port
            except OSError:
                if self.next_port == start:
                    raise RuntimeError("No free ports available for shell listeners")
                continue

    def start_listener(self, session_id: str, target: str, mission_id: str = None, port: int = 0) -> int:
        """Start a TCP listener for a reverse shell on a background thread.

        If port is 0, allocates a dynamic port.
        Returns the port number.
        """
        if port == 0:
            port = self.allocate_port()

        if port in self.listeners:
            logger.warning("Listener already active on port %s", port)
            return port

        # Ensure we have the loop captured
        if not self.loop:
            try:
                self.loop = asyncio.get_running_loop()
            except RuntimeError:
                pass

        # Record listener immediately so callers can see it's active
        self.listeners[port] = None  # Placeholder until socket is created in thread

        def _listen():
            try:
                server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind(("0.0.0.0", port))
                server.listen(1)
                logger.info(
                    "Shell listener started on port %s for session %s",
                    port,
                    session_id,
                )

                self.listeners[port] = server

                conn, addr = server.accept()
                logger.info("Connection received from %s on port %s", addr, port)

                session = ShellSession(session_id, target, mission_id)
                session.socket = conn
                session.active = True
                session._loop = self.loop
                self.sessions[session_id] = session

                # Handle data loop
                while session.active:
                    try:
                        data = conn.recv(SHELL_SOCKET_RECV_BYTES)
                        if not data:
                            break

                        session.broadcast_output(data)

                    except Exception as e:
                        logger.error("Socket error: %s", e)
                        break

                logger.info("Shell session %s ended", session_id)
                if session_id in self.sessions:
                    del self.sessions[session_id]
                if port in self.listeners:
                    del self.listeners[port]
                conn.close()
                server.close()

            except Exception as e:
                logger.error("Listener error on port %s: %s", port, e)
                if port in self.listeners:
                    del self.listeners[port]

        # Start listener thread
        t = threading.Thread(target=_listen, daemon=True)
        t.start()

        return port

    async def get_session(self, session_id: str) -> ShellSession | None:
        return self.sessions.get(session_id)

    def list_sessions(self) -> list[dict]:
        return [
            {
                "id": s.session_id,
                "target": s.target,
                "active": s.active,
                "mission_id": s.mission_id,
                "missions_survived": s.missions_survived,
            }
            for s in self.sessions.values()
        ]

    async def kill_session(self, session_id: str):
        if session_id in self.sessions:
            session = self.sessions[session_id]
            logger.info("Killing shell session %s", session_id)
            if session.socket:
                try:
                    session.socket.shutdown(socket.SHUT_RDWR)
                    session.socket.close()
                except Exception as e:
                    logger.warning(
                        "Error closing socket for session %s: %s",
                        session_id,
                        e,
                    )
            del self.sessions[session_id]

    def notify_mission_complete(self, finished_mission_id: str):
        """Notify that a mission has completed, to update shell TTLs."""
        logger.info("Updating shell TTLs after mission %s complete", finished_mission_id)

        # We need to iterate over a copy of items because we might delete some
        for session_id, session in list(self.sessions.items()):
            # Only increment counter if the shell belongs to a DIFFERENT mission
            # or if it was created in a previous run.
            # If it belongs to the current finished mission, we keep it alive (count=0)
            # until *other* missions pass.

            if session.mission_id != finished_mission_id:
                session.missions_survived += 1
                logger.info(f"Session {session_id} survived {session.missions_survived} missions")

                if session.missions_survived >= 2:
                    logger.info(f"Session {session_id} TTL expired (survived 2 missions). Killing.")
                    # Run kill_session in the event loop since it's async (or just close socket)
                    # Since this method might be called from sync code, we can just close the socket
                    # which will trigger the listener thread to cleanup.
                    if session.socket:
                        try:
                            session.socket.shutdown(socket.SHUT_RDWR)
                            session.socket.close()
                        except Exception as e:
                            logger.debug("Socket cleanup error for expired session: %s", e)


shell_manager = ShellSessionManager()
