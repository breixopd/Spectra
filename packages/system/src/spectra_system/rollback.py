"""
Rollback service — creates snapshots and applies rollbacks for reversible actions.
"""

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_billing.entitlements import sync_user_plan_mirror
from spectra_persistence.models.audit_log import AuditEventType
from spectra_persistence.models.plan import Subscription
from spectra_persistence.models.rollback_snapshot import RollbackSnapshot
from spectra_persistence.models.user import User
from spectra_system.audit import log_event as audit_log_event

logger = logging.getLogger(__name__)


def _subscription_before_state_requires_remote_recreation(subscription_state: object) -> bool:
    if not isinstance(subscription_state, dict):
        return False

    payment_provider = str(subscription_state.get("payment_provider") or "").strip().lower()
    return payment_provider == "stripe" or bool(
        subscription_state.get("external_subscription_id") or subscription_state.get("external_customer_id")
    )


def get_snapshot_restore_blocker(before_state: dict) -> str | None:
    if _subscription_before_state_requires_remote_recreation(before_state.get("subscription")):
        return "Rollback cannot recreate a remotely cancelled Stripe subscription; this snapshot is informational only"
    return None


def describe_snapshot_restorability(snapshot: RollbackSnapshot) -> tuple[bool, str | None]:
    try:
        before_state = json.loads(snapshot.before_state)
    except json.JSONDecodeError:
        return False, "Rollback snapshot payload is invalid"

    if not isinstance(before_state, dict):
        return False, "Rollback snapshot payload is invalid"

    blocker = get_snapshot_restore_blocker(before_state)
    return blocker is None, blocker


def _parse_snapshot_datetime(value: object) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    return datetime.fromisoformat(value)


async def _restore_user_subscription_state(session: AsyncSession, user: User, before_state: dict) -> None:
    current_subscription = (
        await session.execute(select(Subscription).where(Subscription.user_id == str(user.id)))
    ).scalar_one_or_none()

    if "subscription" in before_state:
        snapshot_subscription = before_state["subscription"]
        if snapshot_subscription is None:
            if current_subscription is not None:
                await session.execute(delete(Subscription).where(Subscription.user_id == str(user.id)))
            return

        if not isinstance(snapshot_subscription, dict):
            raise ValueError("Invalid rollback snapshot subscription state")

        if current_subscription is None:
            current_subscription = Subscription(
                user_id=str(user.id),
                plan_id=str(snapshot_subscription["plan_id"]),
                status=str(snapshot_subscription["status"]),
                trial_ends_at=_parse_snapshot_datetime(snapshot_subscription.get("trial_ends_at")),
                current_period_start=_parse_snapshot_datetime(snapshot_subscription.get("current_period_start"))
                or datetime.now(UTC),
                current_period_end=_parse_snapshot_datetime(snapshot_subscription.get("current_period_end")),
                external_subscription_id=snapshot_subscription.get("external_subscription_id"),
                external_customer_id=snapshot_subscription.get("external_customer_id"),
                payment_provider=snapshot_subscription.get("payment_provider"),
                metadata_=snapshot_subscription.get("metadata"),
            )
            session.add(current_subscription)
            return

        current_subscription.plan_id = str(snapshot_subscription["plan_id"])
        current_subscription.status = str(snapshot_subscription["status"])
        current_subscription.trial_ends_at = _parse_snapshot_datetime(snapshot_subscription.get("trial_ends_at"))
        current_subscription.current_period_start = (
            _parse_snapshot_datetime(snapshot_subscription.get("current_period_start"))
            or current_subscription.current_period_start
        )
        current_subscription.current_period_end = _parse_snapshot_datetime(
            snapshot_subscription.get("current_period_end")
        )
        current_subscription.external_subscription_id = snapshot_subscription.get("external_subscription_id")
        current_subscription.external_customer_id = snapshot_subscription.get("external_customer_id")
        current_subscription.payment_provider = snapshot_subscription.get("payment_provider")
        current_subscription.metadata_ = snapshot_subscription.get("metadata")
        return

    legacy_plan_id = before_state.get("plan_id")
    if legacy_plan_id:
        if current_subscription is None:
            session.add(
                Subscription(
                    user_id=str(user.id),
                    plan_id=str(legacy_plan_id),
                    status="active",
                    payment_provider="manual",
                    current_period_start=datetime.now(UTC),
                )
            )
            return

        current_subscription.plan_id = str(legacy_plan_id)
        current_subscription.status = "active"
        current_subscription.current_period_start = datetime.now(UTC)
        current_subscription.current_period_end = None
        if not current_subscription.payment_provider:
            current_subscription.payment_provider = "manual"
        return

    if current_subscription is not None:
        current_subscription.status = "cancelled"
        current_subscription.current_period_end = datetime.now(UTC)


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
    if not isinstance(before_state, dict):
        raise ValueError("Rollback snapshot payload is invalid")

    restore_blocker = get_snapshot_restore_blocker(before_state)
    if restore_blocker is not None:
        raise ValueError(restore_blocker)

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

    if "email" in before_state:
        user.email = before_state["email"]
    if "is_active" in before_state:
        user.is_active = before_state["is_active"]
    if "role" in before_state:
        user.role = before_state["role"]
        user.is_superuser = before_state.get("is_superuser", before_state["role"] == "admin")
    if "plan_id" in before_state or "subscription" in before_state:
        await _restore_user_subscription_state(session, user, before_state)
        await sync_user_plan_mirror(session, user=user)
