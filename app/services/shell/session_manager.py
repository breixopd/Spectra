"""
Shell Session Manager.

Manages active reverse shell connections and bridges them to WebSockets.
Supports multiple routing modes:
  - direct: listen on the app container (legacy default)
  - sandbox: listen inside the mission's sandbox container (preferred)
  - proxy: route through dedicated proxy nodes (future)
"""

from __future__ import annotations

import asyncio
import logging
import socket
import threading
from typing import Any

from fastapi import WebSocket

from app.core.constants import SHELL_SOCKET_RECV_BYTES

logger = logging.getLogger(__name__)

ROUTING_DIRECT = "direct"
ROUTING_SANDBOX = "sandbox"
ROUTING_PROXY = "proxy"


def _get_routing_mode() -> str:
    """Read current routing mode from settings (import deferred to avoid cycles)."""
    from app.core.config import get_settings

    return getattr(get_settings(), "SHELL_ROUTING_MODE", ROUTING_DIRECT)


class ShellSession:
    """Represents an active shell session."""

    def __init__(self, session_id: str, target: str, mission_id: str | None = None):
        self.session_id = session_id
        self.target = target
        self.mission_id = mission_id
        self.missions_survived = 0
        self.socket: socket.socket | None = None
        self.websocket: WebSocket | None = None
        self.active = False
        self.buffer = b""
        self._loop: asyncio.AbstractEventLoop | None = None
        self.routing_mode: str = ROUTING_DIRECT
        # Container-backed sessions store the Docker exec process handle
        self._exec_handle: Any = None
        self._relay_task: asyncio.Task | None = None

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
        """Write data to the shell socket (direct mode) or exec stdin (sandbox mode)."""
        if self.routing_mode == ROUTING_SANDBOX and self._exec_handle:
            try:
                sock = self._exec_handle.output
                sock.sendall(data.encode())
            except OSError as e:
                logger.error("Failed to write to sandbox exec socket: %s", e)
                self.active = False
        elif self.socket:
            try:
                self.socket.sendall(data.encode())
            except OSError as e:
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
            except OSError as e:
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
        self.listeners: dict[int, socket.socket | None] = {}

        # Range for dynamic port allocation
        from app.core.constants import SHELL_CALLBACK_PORT_END, SHELL_CALLBACK_PORT_START

        self.port_range_start = SHELL_CALLBACK_PORT_START
        self.port_range_end = SHELL_CALLBACK_PORT_END
        self.next_port = self.port_range_start

    def _ensure_loop(self) -> None:
        if not self.loop:
            try:
                self.loop = asyncio.get_running_loop()
            except RuntimeError:
                pass

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
                sock.bind(("127.0.0.1", port))
                sock.close()
                return port
            except OSError:
                if self.next_port == start:
                    raise RuntimeError("No free ports available for shell listeners")
                continue

    # ------------------------------------------------------------------
    # Public entry point — dispatches to the right mode
    # ------------------------------------------------------------------

    def start_listener(self, session_id: str, target: str, mission_id: str | None = None, port: int = 0) -> int:
        """Start a shell listener using the configured routing mode.

        Returns the port number the listener is bound on.
        """
        mode = _get_routing_mode()
        if mode == ROUTING_SANDBOX and mission_id:
            return self._start_sandbox_listener(session_id, target, mission_id, port)
        # proxy mode falls back to direct until implemented
        if mode == ROUTING_PROXY:
            logger.warning("Proxy routing not yet implemented, falling back to direct mode")
        return self._start_direct_listener(session_id, target, mission_id, port)

    # ------------------------------------------------------------------
    # Direct mode — listen on the app container (original behaviour)
    # ------------------------------------------------------------------

    def _start_direct_listener(self, session_id: str, target: str, mission_id: str | None, port: int) -> int:
        if port == 0:
            port = self.allocate_port()

        if port in self.listeners:
            logger.warning("Listener already active on port %s", port)
            return port

        self._ensure_loop()
        self.listeners[port] = None  # Placeholder

        def _listen():
            try:
                server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind(("127.0.0.1", port))
                server.listen(1)
                logger.info("Shell listener started on port %s for session %s", port, session_id)

                self.listeners[port] = server

                conn, addr = server.accept()
                logger.info("Connection received from %s on port %s", addr, port)

                session = ShellSession(session_id, target, mission_id)
                session.socket = conn
                session.active = True
                session.routing_mode = ROUTING_DIRECT
                session._loop = self.loop
                self.sessions[session_id] = session

                while session.active:
                    try:
                        data = conn.recv(SHELL_SOCKET_RECV_BYTES)
                        if not data:
                            break
                        session.broadcast_output(data)
                    except OSError as e:
                        logger.error("Socket error: %s", e)
                        break

                logger.info("Shell session %s ended", session_id)
                self.sessions.pop(session_id, None)
                self.listeners.pop(port, None)
                conn.close()
                server.close()
            except OSError as e:
                logger.error("Listener error on port %s: %s", port, e)
                self.listeners.pop(port, None)

        t = threading.Thread(target=_listen, daemon=True)
        t.start()
        return port

    # ------------------------------------------------------------------
    # Sandbox mode — run socat inside the mission's sandbox container
    # ------------------------------------------------------------------

    def _start_sandbox_listener(self, session_id: str, target: str, mission_id: str, port: int) -> int:
        """Start a TCP listener inside the sandbox container via Docker exec.

        socat inside the container listens on the requested port. A relay
        thread reads its stdout and pipes data to the ShellSession, which
        forwards it to the WebSocket.
        """
        if port == 0:
            port = self.allocate_port()

        if port in self.listeners:
            logger.warning("Listener already active on port %s", port)
            return port

        self._ensure_loop()
        self.listeners[port] = None

        def _sandbox_listen():
            try:
                container = self._get_sandbox_container(mission_id)
                if container is None:
                    logger.error("No sandbox container found for mission %s — falling back to direct", mission_id[:8])
                    self.listeners.pop(port, None)
                    # Fallback: start a direct listener instead
                    self._start_direct_listener(session_id, target, mission_id, port)
                    return

                # Launch socat inside the sandbox: listen on TCP port, relay via stdin/stdout
                cmd = f"socat TCP-LISTEN:{port},reuseaddr,fork STDIO"
                exec_handle = container.exec_run(
                    cmd, stdin=True, stdout=True, stderr=True, stream=True, socket=True, demux=False
                )

                logger.info(
                    "Sandbox shell listener on port %s in container %s for session %s",
                    port,
                    container.name,
                    session_id,
                )

                session = ShellSession(session_id, target, mission_id)
                session.active = True
                session.routing_mode = ROUTING_SANDBOX
                session._exec_handle = exec_handle
                session._loop = self.loop
                self.sessions[session_id] = session

                # Read output from exec socket
                try:
                    raw_sock = exec_handle.output
                    while session.active:
                        data = raw_sock.recv(SHELL_SOCKET_RECV_BYTES)
                        if not data:
                            break
                        session.broadcast_output(data)
                except OSError as e:
                    logger.error("Sandbox relay error for session %s: %s", session_id, e)

                logger.info("Sandbox shell session %s ended", session_id)
                self.sessions.pop(session_id, None)
                self.listeners.pop(port, None)
                try:
                    raw_sock.close()
                except OSError:
                    pass  # Socket already closed
            except OSError as e:
                logger.error("Sandbox listener error for session %s: %s", session_id, e)
                self.listeners.pop(port, None)

        t = threading.Thread(target=_sandbox_listen, daemon=True)
        t.start()
        return port

    @staticmethod
    def _get_sandbox_container(mission_id: str) -> Any:
        """Look up the running Docker container for a mission's sandbox."""
        try:
            import docker

            client = docker.from_env()
            container_name = f"spectra-sandbox-{mission_id[:8]}"
            return client.containers.get(container_name)
        except (OSError, RuntimeError) as e:
            logger.debug("Could not find sandbox container for mission %s: %s", mission_id[:8], e)
            return None

    # ------------------------------------------------------------------
    # Session management (unchanged across modes)
    # ------------------------------------------------------------------

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
                "routing_mode": s.routing_mode,
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
                except OSError as e:
                    logger.warning("Error closing socket for session %s: %s", session_id, e)
            if session._exec_handle:
                try:
                    session._exec_handle.output.close()
                except OSError:
                    pass  # Handle already closed
            session.active = False
            del self.sessions[session_id]

    def notify_mission_complete(self, finished_mission_id: str):
        """Notify that a mission has completed, to update shell TTLs."""
        logger.info("Updating shell TTLs after mission %s complete", finished_mission_id)

        for session_id, session in list(self.sessions.items()):
            if session.mission_id != finished_mission_id:
                session.missions_survived += 1
                logger.info(f"Session {session_id} survived {session.missions_survived} missions")

                if session.missions_survived >= 2:
                    logger.info(f"Session {session_id} TTL expired (survived 2 missions). Killing.")
                    if session.socket:
                        try:
                            session.socket.shutdown(socket.SHUT_RDWR)
                            session.socket.close()
                        except OSError as e:
                            logger.debug("Socket cleanup error for expired session: %s", e)
                    if session._exec_handle:
                        try:
                            session._exec_handle.output.close()
                        except OSError:
                            pass  # Handle already closed


shell_manager = ShellSessionManager()
