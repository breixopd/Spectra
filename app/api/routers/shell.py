"""
Shell Router.

Handles WebSocket connections for interactive shells.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.api.dependencies import check_feature_allowed, get_current_active_user, validate_websocket_token
from app.auth.rate_limit import RateLimits, limiter
from spectra_common.constants import WS_KEEPALIVE_INTERVAL, WS_MAX_MESSAGE_SIZE, WS_MAX_MESSAGES_PER_SECOND
from app.core.database import async_session_maker
from app.infrastructure.tasks import create_safe_task
from app.models.audit_log import AuditEventType
from app.models.finding import Finding
from app.models.mission import Mission
from app.models.user import User
from app.services.shell.relay_client import shell_relay_client
from app.services.shell.session_manager import shell_manager
from app.services.system.audit import log_event as audit_log_event

router = APIRouter(prefix="/shell", tags=["Shell"])
logger = logging.getLogger(__name__)

_SHELL_SESSION_ID_RE = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")


def _validate_shell_session_id(session_id: str) -> str:
    if not _SHELL_SESSION_ID_RE.fullmatch(session_id):
        raise HTTPException(status_code=422, detail="Invalid session ID format")
    return session_id


async def _keepalive(websocket: WebSocket) -> None:
    """Send periodic pings to keep the WebSocket connection alive."""
    try:
        while True:
            await asyncio.sleep(WS_KEEPALIVE_INTERVAL)
            await websocket.send_json({"type": "ping"})
    except OSError:
        pass


@router.websocket("/{session_id}")
async def shell_websocket(websocket: WebSocket, session_id: str, token: str | None = Query(default=None)):
    session_id = _validate_shell_session_id(session_id)
    # Prefer query-param token, fall back to cookie
    ws_token = token
    if not ws_token:
        ws_token = websocket.cookies.get("access_token")
    user = await validate_websocket_token(ws_token)
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
    if not user.is_superuser:
        if not session.mission_id:
            await websocket.close(code=4003, reason="Not authorized for this session")
            return
        async with async_session_maker() as db:
            result = await db.execute(select(Mission).where(Mission.id == session.mission_id))
            mission = result.scalar_one_or_none()
            if not mission or not mission.user_id or mission.user_id != str(user.id):
                await websocket.close(code=4003, reason="Not authorized for this session")
                return

    await session.connect_websocket(websocket)

    ping_task = create_safe_task(_keepalive(websocket), name="ws-keepalive")
    message_count = 0
    last_reset = time.time()
    try:
        while True:
            data = await websocket.receive_text()

            # Per-second message rate limiting
            now = time.time()
            if now - last_reset >= 1.0:
                message_count = 0
                last_reset = now
            message_count += 1
            if message_count > WS_MAX_MESSAGES_PER_SECOND:
                await websocket.send_json({"type": "error", "message": "Rate limit exceeded"})
                continue

            # Validate message size (DoS protection)
            if len(data) > WS_MAX_MESSAGE_SIZE:
                await websocket.send_json({"type": "error", "message": "Message too large"})
                continue

            await session.write(data)
    except WebSocketDisconnect:
        await session.disconnect_websocket()
    except (OSError, RuntimeError, ConnectionError) as e:
        logger.error("WebSocket error: %s", e)
        await session.disconnect_websocket()
    finally:
        ping_task.cancel()


@router.get("/sessions")
@limiter.limit(RateLimits.SHELL_SESSIONS)
async def list_sessions(request: Request, _current_user: User = Depends(get_current_active_user)):
    """List active shell sessions (scoped to the user's missions)."""
    all_sessions = shell_manager.list_sessions()
    if _current_user.is_superuser:
        return all_sessions

    # Filter to sessions belonging to the user's missions
    user_id = str(_current_user.id)
    async with async_session_maker() as db:
        result = await db.execute(select(Mission.id).where(Mission.user_id == user_id))
        user_mission_ids = {row[0] for row in result.all()}

    return [s for s in all_sessions if not s.get("mission_id") or s["mission_id"] in user_mission_ids]


@router.get("/listeners")
@limiter.limit(RateLimits.SHELL_SESSIONS)
async def list_listeners(request: Request, _current_user: User = Depends(get_current_active_user)):
    """List managed callback listeners with TTLs, scoped to the user's missions."""
    try:
        all_listeners = await shell_relay_client.list_listeners()
    except Exception as exc:
        logger.warning("Worker listener inventory unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="Worker listener service unavailable") from exc
    if _current_user.is_superuser:
        return all_listeners

    user_id = str(_current_user.id)
    async with async_session_maker() as db:
        result = await db.execute(select(Mission.id).where(Mission.user_id == user_id))
        user_mission_ids = {row[0] for row in result.all()}
    return [item for item in all_listeners if item.get("mission_id") in user_mission_ids]


@router.delete("/listeners/{session_id}", status_code=204)
async def stop_listener(session_id: str, _current_user: User = Depends(get_current_active_user)) -> None:
    """Stop a managed callback listener."""
    try:
        listeners = await shell_relay_client.list_listeners()
    except Exception as exc:
        logger.warning("Worker listener inventory unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="Worker listener service unavailable") from exc
    listener = next((item for item in listeners if item.get("session_id") == session_id), None)
    if not listener:
        raise HTTPException(status_code=404, detail="Listener not found")

    if not _current_user.is_superuser:
        mission_id = listener.get("mission_id")
        async with async_session_maker() as db:
            result = await db.execute(select(Mission.id).where(Mission.id == mission_id, Mission.user_id == str(_current_user.id)))
            if result.scalar_one_or_none() is None:
                raise HTTPException(status_code=403, detail="Not authorized to stop this listener")
    if not await shell_relay_client.stop_listener(session_id):
        raise HTTPException(status_code=404, detail="Listener not found")


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
