"""
Shell Router.

Handles WebSocket connections for interactive shells.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from app.services.shell.session_manager import shell_manager
import logging

router = APIRouter(prefix="/shell", tags=["Shell"])
logger = logging.getLogger("spectra.api.shell")

@router.websocket("/{session_id}")
async def shell_websocket(websocket: WebSocket, session_id: str):
    await websocket.accept()

    session = await shell_manager.get_session(session_id)
    if not session:
        await websocket.close(code=1000, reason="Session not found")
        return

    await session.connect_websocket(websocket)

    try:
        while True:
            data = await websocket.receive_text()
            # Send to shell socket
            await session.write(data)
    except WebSocketDisconnect:
        await session.disconnect_websocket()
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await session.disconnect_websocket()
