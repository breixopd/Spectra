"""
Shell Router.

Handles WebSocket connections for interactive shells.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from app.services.shell.session_manager import shell_manager
from app.models.finding import Finding
from sqlalchemy import select
from app.core.database import async_session_maker
import logging

router = APIRouter(prefix="", tags=["Shell"]) # Prefix is handled in main.py
logger = logging.getLogger("spectra.api.shell")

@router.websocket("/{session_id}")
async def shell_websocket(websocket: WebSocket, session_id: str):
    await websocket.accept()

    session = await shell_manager.get_session(session_id)
    if not session:
        # Check if it's a valid session ID for reconnection?
        # For now, just close. The "Reconnect" feature will be an API call
        # that spawns a NEW session, not connecting to a dead one.
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

@router.get("/sessions")
async def list_sessions():
    """List active shell sessions."""
    return shell_manager.list_sessions()

@router.post("/reconnect/{finding_id}")
async def reconnect_exploit(finding_id: str):
    """
    Trigger a re-exploitation of a vulnerability to re-establish a shell.

    This is a simplified implementation. Ideally, this would spawn an async task
    managed by MissionExecutor, but for ad-hoc access, we'll try to use the
    ExploitationManager directly if possible, or trigger a new mini-mission.
    """
    # 1. Fetch finding to get exploit details
    async with async_session_maker() as session:
        result = await session.execute(select(Finding).where(Finding.id == finding_id))
        finding = result.scalar_one_or_none()

    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    directive = f"Exploit vulnerability at {finding.location} using {finding.tool_name} to get a shell."

    # Return instructions to frontend to start a new mission
    return {
        "status": "triggered",
        "message": "To reconnect, please start a new targeted mission.",
        "suggested_directive": directive,
        "target": finding.location
    }
