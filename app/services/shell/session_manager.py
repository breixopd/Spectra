"""
Shell Session Manager.

Manages active reverse shell connections and bridges them to WebSockets.
"""

import asyncio
import logging
import socket
import threading
from typing import Dict, Optional
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("spectra.shell.manager")


class ShellSession:
    """Represents an active shell session."""

    def __init__(self, session_id: str, target: str):
        self.session_id = session_id
        self.target = target
        self.socket: Optional[socket.socket] = None
        self.websocket: Optional[WebSocket] = None
        self.active = False
        self.buffer = b""
        self._loop = None # Reference to main event loop

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
                logger.error(f"Failed to write to shell socket: {e}")
                self.active = False

    def broadcast_output(self, data: bytes):
        """Broadcast output to websocket if connected."""
        if not data:
            return

        if self.websocket and self._loop:
            try:
                text = data.decode("utf-8", errors="replace")
                asyncio.run_coroutine_threadsafe(
                    self.websocket.send_text(text),
                    self._loop
                )
            except Exception as e:
                logger.error(f"Failed to broadcast output: {e}")
        else:
            # Buffer if no listener
            self.buffer += data


class ShellSessionManager:
    """Singleton manager for shell sessions."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ShellSessionManager, cls).__new__(cls)
            cls._instance.sessions = {}  # type: ignore
            cls._instance.listeners = {}  # type: ignore
            cls._instance.loop = asyncio.get_event_loop() # Capture main loop
        return cls._instance

    def __init__(self):
        self.sessions: Dict[str, ShellSession] = {}
        self.listeners: Dict[int, socket.socket] = {}
        self.loop = None

    def start_listener(self, port: int, session_id: str, target: str) -> None:
        """Start a TCP listener for a reverse shell on a background thread."""
        if port in self.listeners:
            logger.warning(f"Listener already active on port {port}")
            return

        # Ensure we have the loop captured
        if not self.loop:
             try:
                 self.loop = asyncio.get_running_loop()
             except RuntimeError:
                 pass

        def _listen():
            try:
                server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind(("0.0.0.0", port))
                server.listen(1)
                logger.info(f"Shell listener started on port {port} for session {session_id}")

                self.listeners[port] = server

                conn, addr = server.accept()
                logger.info(f"Connection received from {addr} on port {port}")

                session = ShellSession(session_id, target)
                session.socket = conn
                session.active = True
                session._loop = self.loop
                self.sessions[session_id] = session

                # Handle data loop
                while session.active:
                    try:
                        data = conn.recv(4096)
                        if not data:
                            break

                        session.broadcast_output(data)

                    except Exception as e:
                        logger.error(f"Socket error: {e}")
                        break

                logger.info(f"Shell session {session_id} ended")
                if session_id in self.sessions:
                    del self.sessions[session_id]
                if port in self.listeners:
                    del self.listeners[port]
                conn.close()
                server.close()

            except Exception as e:
                logger.error(f"Listener error on port {port}: {e}")
                if port in self.listeners:
                    del self.listeners[port]

        # Start listener thread
        t = threading.Thread(target=_listen, daemon=True)
        t.start()

    async def get_session(self, session_id: str) -> Optional[ShellSession]:
        return self.sessions.get(session_id)

    def list_sessions(self) -> list[dict]:
        return [
            {"id": s.session_id, "target": s.target, "active": s.active}
            for s in self.sessions.values()
        ]

    async def kill_session(self, session_id: str):
        if session_id in self.sessions:
            session = self.sessions[session_id]
            if session.socket:
                session.socket.close()
            del self.sessions[session_id]

shell_manager = ShellSessionManager()
