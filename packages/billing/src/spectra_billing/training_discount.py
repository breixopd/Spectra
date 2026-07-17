"""Training data sharing discount — rewards users who opt in to share anonymized data.

Users enabling training_opt_in receive a plan discount. The opt-in is locked
until their subscription renewal date to prevent abuse (enabling for discount,
disabling immediately after). Once locked, disabling is only permitted after
the current billing period ends.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

logger = logging.getLogger(__name__)

# Default discount percentage for training data opt-in
TRAINING_OPT_IN_DISCOUNT_PCT = 10.0  # 10% off


async def calculate_training_discount(
    session,
    user_id: str,
) -> float:
    """Calculate the training data sharing discount for a user.

    Returns the discount percentage (0.0 to 100.0) applicable to this user.
    Only active if user has opted in and has an active paid subscription.
    """
    from spectra_persistence.models.subscription import Subscription
    from spectra_persistence.models.user import User

    result = await session.execute(select(User.training_opt_in).where(User.id == user_id))
    row = result.one_or_none()
    if row is None or not row[0]:
        return 0.0

    # Check if user has an active paid subscription
    sub_result = await session.execute(
        select(Subscription.status).where(
            Subscription.user_id == user_id,
            Subscription.status == "active",
        )
    )
    sub_row = sub_result.one_or_none()
    if sub_row is None:
        return 0.0

    return TRAINING_OPT_IN_DISCOUNT_PCT


async def lock_training_opt_in(
    session,
    user_id: str,
) -> bool:
    """Lock the training opt-in until the next subscription renewal.

    Called when user enables training_opt_in. Sets training_opt_in_locked_until
    to the subscription's current_period_end, preventing opt-out until renewal.

    Returns True if locked successfully, False if no active subscription.
    """

    from spectra_persistence.models.subscription import Subscription
    from spectra_persistence.models.user import User

    sub_result = await session.execute(
        select(Subscription.current_period_end).where(
            Subscription.user_id == user_id,
            Subscription.status == "active",
        )
    )
    sub_row = sub_result.one_or_none()

    if sub_row is None or sub_row[0] is None:
        # No active subscription — lock for 30 days as fallback
        lock_until = datetime.now(UTC).replace(tzinfo=None)
        from datetime import timedelta

        lock_until = lock_until + timedelta(days=30)
    else:
        lock_until = sub_row[0]
        if lock_until.tzinfo is not None:
            lock_until = lock_until.replace(tzinfo=None)

    user_result = await session.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        return False

    user.training_opt_in = True
    user.training_opt_in_locked_until = lock_until
    await session.flush()

    logger.info(
        "Training opt-in locked for user %s until %s",
        user_id,
        lock_until.isoformat() if lock_until else "N/A",
    )
    return True


async def can_disable_training_opt_in(
    session,
    user_id: str,
) -> tuple[bool, str]:
    """Check if user can disable training_opt_in.

    Returns (can_disable, reason).
    False if the opt-in is locked until a future date.
    """

    from spectra_persistence.models.user import User

    result = await session.execute(
        select(User.training_opt_in, User.training_opt_in_locked_until).where(User.id == user_id)
    )
    row = result.one_or_none()
    if row is None:
        return False, "User not found"

    opt_in, locked_until = row
    if not opt_in:
        return True, "Already disabled"

    if locked_until is None:
        return True, "Not locked"

    now = datetime.now(UTC).replace(tzinfo=None)
    if locked_until > now:
        return False, (
            f"Training data sharing is locked until {locked_until.strftime('%Y-%m-%d')}. "
            f"You received a {TRAINING_OPT_IN_DISCOUNT_PCT:.0f}% discount for this period. "
            f"It can be disabled after renewal."
        )

    return True, "Lock period expired"


async def disable_training_opt_in(
    session,
    user_id: str,
) -> dict[str, Any]:
    """Disable training_opt_in if not locked.

    Returns dict with success status and message.
    """
    from spectra_persistence.models.user import User

    can_disable, reason = await can_disable_training_opt_in(session, user_id)
    if not can_disable:
        return {"success": False, "message": reason, "locked": True}

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        return {"success": False, "message": "User not found"}

    user.training_opt_in = False
    user.training_opt_in_locked_until = None
    await session.flush()

    logger.info("Training opt-in disabled for user %s", user_id)
    return {"success": True, "message": "Training data sharing disabled", "locked": False}
