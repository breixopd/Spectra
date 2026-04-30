"""Admin rollback endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Permission, require_permission
from app.core.database import get_async_session
from app.models.user import User
from app.services.system.rollback import describe_snapshot_restorability, get_all_snapshots, rollback_snapshot

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Admin Rollback"])


@router.get("/api/admin/rollback/snapshots")
async def list_rollback_snapshots(
    limit: int = Query(default=50, le=200),
    session: AsyncSession = Depends(get_async_session),
    admin: User = require_permission(Permission.MANAGE_USERS),
):
    """List all pending (not yet rolled back) snapshots. Admin only."""
    snapshots = await get_all_snapshots(session, limit=limit)
    items = []
    for snapshot in snapshots:
        restorable, restore_error = describe_snapshot_restorability(snapshot)
        items.append(
            {
                "id": str(snapshot.id),
                "actor_user_id": snapshot.actor_user_id,
                "entity_type": snapshot.target_entity_type,
                "entity_id": snapshot.target_entity_id,
                "action": snapshot.action,
                "created_at": snapshot.created_at.isoformat(),
                "restorable": restorable,
                "restore_error": restore_error,
            }
        )
    return items


@router.post("/api/admin/rollback/snapshots/{snapshot_id}/rollback")
async def apply_rollback(
    snapshot_id: str,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    admin: User = require_permission(Permission.MANAGE_USERS),
):
    """Roll back a specific snapshot. Admin only."""
    try:
        before_state = await rollback_snapshot(session, snapshot_id, str(admin.id), request)
        # audit_log_event already commits; this is a safe no-op if nothing remains
        await session.commit()
        return {"status": "rolled_back", "restored": before_state}
    except ValueError as exc:
        logger.warning("Rollback operation rejected for snapshot %s: %s", snapshot_id, exc)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except Exception as e:
        logger.error("Rollback failed for snapshot %s: %s", snapshot_id, e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Rollback failed")
