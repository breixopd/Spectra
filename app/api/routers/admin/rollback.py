"""Admin rollback endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.rbac import Permission, require_permission
from app.models.user import User
from app.services.system.rollback import get_all_snapshots, rollback_snapshot

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/rollback", tags=["Admin Rollback"])


@router.get("/snapshots")
async def list_rollback_snapshots(
    limit: int = Query(default=50, le=200),
    session: AsyncSession = Depends(get_async_session),
    admin: User = require_permission(Permission.MANAGE_USERS),
):
    """List all pending (not yet rolled back) snapshots. Admin only."""
    snapshots = await get_all_snapshots(session, limit=limit)
    return [
        {
            "id": str(s.id),
            "actor_user_id": s.actor_user_id,
            "entity_type": s.target_entity_type,
            "entity_id": s.target_entity_id,
            "action": s.action,
            "created_at": s.created_at.isoformat(),
        }
        for s in snapshots
    ]


@router.post("/snapshots/{snapshot_id}/rollback")
async def apply_rollback(
    snapshot_id: str,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    admin: User = require_permission(Permission.MANAGE_USERS),
):
    """Roll back a specific snapshot. Admin only."""
    try:
        before_state = await rollback_snapshot(
            session, snapshot_id, str(admin.id), request
        )
        # audit_log_event already commits; this is a safe no-op if nothing remains
        await session.commit()
        return {"status": "rolled_back", "restored": before_state}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
