"""OOM-based automatic resource tier escalation for sandbox containers."""

from __future__ import annotations

import logging

from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.database import async_session_maker
from app.models.infrastructure import Sandbox

logger = logging.getLogger(__name__)

# Tier escalation path — each tier escalates to the next
TIER_ESCALATION_PATH = {
    "light": "medium",
    "medium": "heavy",
    "heavy": "extreme",
    # "extreme" has no next tier — OOM at extreme is a permanent failure
}


def next_tier(current_tier: str) -> str | None:
    """Get the next resource tier for escalation, or None if at maximum."""
    return TIER_ESCALATION_PATH.get(current_tier)


async def attempt_oom_escalation(mission_id: str) -> tuple[bool, str]:
    """Attempt to escalate a sandbox to the next resource tier after OOM.

    Returns:
        (success, message) tuple. success=True if escalation was performed.
    """
    settings = get_settings()
    if not settings.SANDBOX_OOM_ESCALATION_ENABLED:
        return False, "OOM escalation is disabled"

    async with async_session_maker() as session:
        result = await session.execute(
            select(Sandbox).where(
                Sandbox.mission_id == mission_id,
                Sandbox.status.in_(["running", "error"]),
            )
        )
        sandbox = result.scalar_one_or_none()

        if not sandbox:
            return False, f"No active sandbox found for mission {mission_id[:8]}"

        if sandbox.escalated:
            return False, f"Sandbox already escalated once (tier={sandbox.resource_tier}), cannot escalate again"

        current_tier = sandbox.resource_tier or "medium"
        new_tier = next_tier(current_tier)

        if not new_tier:
            return False, f"Already at maximum tier ({current_tier}), cannot escalate"

        # Mark current sandbox as escalated
        await session.execute(update(Sandbox).where(Sandbox.id == sandbox.id).values(escalated=True))
        await session.commit()

    # Destroy current sandbox and recreate at new tier
    from app.services.tools.sandbox import get_sandbox_pool

    pool = get_sandbox_pool()
    if not pool:
        return False, "Sandbox pool not available"

    logger.warning(
        "OOM escalation: mission=%s, %s → %s",
        mission_id[:8],
        current_tier,
        new_tier,
    )

    # Destroy old sandbox
    await pool.destroy(mission_id)

    # Create new sandbox at higher tier
    await pool.create(
        mission_id,
        resource_tier=new_tier,
        user_id=sandbox.user_id,
    )

    return True, f"Escalated from {current_tier} to {new_tier}"
