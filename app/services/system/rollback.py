"""
Rollback service — creates snapshots and applies rollbacks for reversible actions.
"""

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditEventType
from app.models.rollback_snapshot import RollbackSnapshot
from app.models.user import User
from app.services.system.audit import log_event as audit_log_event

logger = logging.getLogger(__name__)


async def create_snapshot(
    session: AsyncSession,
    actor_user_id: str,
    entity_type: str,
    entity_id: str,
    action: str,
    before_state: dict,
) -> RollbackSnapshot:
    """Create a rollback snapshot before performing a reversible action."""
    snapshot = RollbackSnapshot(
        actor_user_id=actor_user_id,
        target_entity_type=entity_type,
        target_entity_id=entity_id,
        action=action,
        before_state=json.dumps(before_state),
    )
    session.add(snapshot)
    await session.flush()  # get ID without committing
    return snapshot


async def get_snapshots_by_actor(
    session: AsyncSession,
    actor_user_id: str,
    limit: int = 50,
) -> list[RollbackSnapshot]:
    """Get recent snapshots for a specific actor (for operator self-view)."""
    result = await session.execute(
        select(RollbackSnapshot)
        .where(RollbackSnapshot.actor_user_id == actor_user_id)
        .where(RollbackSnapshot.rolled_back.is_(False))
        .order_by(RollbackSnapshot.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_all_snapshots(
    session: AsyncSession,
    limit: int = 100,
) -> list[RollbackSnapshot]:
    """Get all recent snapshots for admin view."""
    result = await session.execute(
        select(RollbackSnapshot)
        .where(RollbackSnapshot.rolled_back.is_(False))
        .order_by(RollbackSnapshot.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def rollback_snapshot(
    session: AsyncSession,
    snapshot_id: str,
    admin_user_id: str,
    request=None,
) -> dict:
    """Apply a rollback for a snapshot. Returns the before_state dict."""
    result = await session.execute(select(RollbackSnapshot).where(RollbackSnapshot.id == snapshot_id))
    snapshot = result.scalar_one_or_none()
    if not snapshot:
        raise ValueError(f"Snapshot {snapshot_id} not found")
    if snapshot.rolled_back:
        raise ValueError(f"Snapshot {snapshot_id} has already been rolled back")

    before_state = json.loads(snapshot.before_state)

    # Apply rollback based on entity type
    if snapshot.target_entity_type == "user":
        await _rollback_user(session, snapshot.target_entity_id, before_state)
    else:
        raise ValueError(f"Rollback not supported for entity type: {snapshot.target_entity_type}")

    # Mark as rolled back
    snapshot.rolled_back = True
    snapshot.rolled_back_by = admin_user_id
    snapshot.rolled_back_at = datetime.now(UTC)

    # Audit log (this will commit the session)
    await audit_log_event(
        session,
        AuditEventType.ROLLBACK_PERFORMED,
        user_id=admin_user_id,
        details={
            "snapshot_id": snapshot_id,
            "entity_type": snapshot.target_entity_type,
            "entity_id": snapshot.target_entity_id,
            "original_action": snapshot.action,
            "actor": snapshot.actor_user_id,
        },
        request=request,
    )

    return before_state


async def _rollback_user(session: AsyncSession, user_id: str, before_state: dict) -> None:
    """Restore user fields from a before_state snapshot."""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError(f"User {user_id} not found for rollback")

    if "is_active" in before_state:
        user.is_active = before_state["is_active"]
    if "role" in before_state:
        user.role = before_state["role"]
        user.is_superuser = before_state.get("is_superuser", before_state["role"] == "admin")
    if "plan_id" in before_state:
        user.plan_id = before_state["plan_id"]
