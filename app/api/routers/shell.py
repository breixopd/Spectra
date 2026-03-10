"""
Shell Router.

Handles WebSocket connections for interactive shells.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.api.dependencies import check_feature_allowed, get_current_active_user, validate_websocket_token
from app.core.database import async_session_maker
from app.models.audit_log import AuditEventType
from app.models.finding import Finding
from app.models.mission import Mission
from app.models.user import User
from app.services.shell.session_manager import shell_manager
from app.services.system.audit import log_event as audit_log_event

router = APIRouter(prefix="/shell", tags=["Shell"])
logger = logging.getLogger("spectra.api.shell")


@router.websocket("/{session_id}")
async def shell_websocket(websocket: WebSocket, session_id: str, token: str | None = Query(default=None)):
    user = await validate_websocket_token(token)
    if not user:
        await websocket.close(code=4001, reason="Authentication required")
        return
    await websocket.accept()

    # Check shell_access feature
    try:
        async with async_session_maker() as db:
            await check_feature_allowed(user, db, "shell_access")
    except HTTPException:
        await websocket.close(code=4003, reason="Shell access not available on your plan")
        return

    logger.info("Shell WebSocket connected: user=%s session=%s", user.username, session_id)
    async with async_session_maker() as db:
        await audit_log_event(
            db,
            AuditEventType.SHELL_CONNECT,
            user_id=str(user.id),
            details={"session_id": session_id},
        )

    session = await shell_manager.get_session(session_id)
    if not session:
        # Check if it's a valid session ID for reconnection?
        # Close the connection
        # that spawns a NEW session, not connecting to a dead one.
        await websocket.close(code=1000, reason="Session not found")
        return

    # Verify the user owns the mission associated with this shell session
    if session.mission_id and not user.is_superuser:
        async with async_session_maker() as db:
            result = await db.execute(
                select(Mission).where(Mission.id == session.mission_id)
            )
            mission = result.scalar_one_or_none()
            if mission and mission.user_id and mission.user_id != str(user.id):
                await websocket.close(code=4003, reason="Not authorized for this session")
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
        logger.error("WebSocket error: %s", e)
        await session.disconnect_websocket()


@router.get("/sessions")
async def list_sessions(_current_user: User = Depends(get_current_active_user)):
    """List active shell sessions (scoped to the user's missions)."""
    all_sessions = shell_manager.list_sessions()
    if _current_user.is_superuser:
        return all_sessions

    # Filter to sessions belonging to the user's missions
    user_id = str(_current_user.id)
    async with async_session_maker() as db:
        result = await db.execute(
            select(Mission.id).where(Mission.user_id == user_id)
        )
        user_mission_ids = {row[0] for row in result.all()}

    return [
        s for s in all_sessions
        if not s.get("mission_id") or s["mission_id"] in user_mission_ids
    ]


@router.post("/reconnect/{finding_id}")
async def reconnect_exploit(finding_id: str, _current_user: User = Depends(get_current_active_user)):
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

    # Check shell_access feature
    async with async_session_maker() as db:
        await check_feature_allowed(_current_user, db, "shell_access")

    # User isolation: non-superusers can only reconnect to their own findings
    if not _current_user.is_superuser and finding.user_id and finding.user_id != str(_current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized to access this finding")

    logger.info("Exploit reconnect requested: user=%s finding=%s", _current_user.username, finding_id)
    async with async_session_maker() as db:
        await audit_log_event(
            db,
            AuditEventType.EXPLOIT_RECONNECT,
            user_id=str(_current_user.id),
            details={"finding_id": finding_id, "target": finding.target_id},
        )

    directive = f"Exploit vulnerability at {finding.target_id} using {finding.tool_source} to get a shell."

    # Return instructions to frontend to start a new mission
    return {
        "status": "triggered",
        "message": "To reconnect, please start a new targeted mission.",
        "suggested_directive": directive,
        "target": finding.target_id,
    }
