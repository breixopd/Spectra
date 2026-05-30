"""Consensus / voting logic for high-risk tool execution."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spectra_ai_core.consensus import VotingSystem
    from spectra_mission.mission import Mission

logger = logging.getLogger(__name__)


async def perform_consensus_check(
    mission: Mission,
    tool_name: str,
    risk_level: str,
    consensus: VotingSystem,
) -> bool:
    """Get consensus for high-risk actions."""
    mission.log(f"[VOTE] High-risk action: {tool_name} ({risk_level})")

    from spectra_ai_core.agents.base import ActionRisk, AgentAction

    proxy_action = AgentAction(
        action_type="tool_execution",
        risk_level=ActionRisk.HIGH if risk_level == "high" else ActionRisk.CRITICAL,
        confidence=1.0,
        reasoning=f"Execute high-risk tool {tool_name}",
    )

    vote_result = await consensus.vote_on_action(
        proxy_action,
        {"target": mission.target, "tool": tool_name},
    )

    if vote_result.status != "approved":
        mission.log(f"[REJECTED] Action blocked by consensus: {vote_result.escalation_reason}")
        return False

    mission.log("[APPROVED] Action validated by consensus")
    return True
