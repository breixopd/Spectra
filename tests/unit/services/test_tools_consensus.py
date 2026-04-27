import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.tools.consensus import perform_consensus_check
from app.services.ai.agents.base import ActionRisk


@pytest.mark.asyncio
async def test_perform_consensus_check_approved():
    mission = MagicMock()
    mission.log = MagicMock()
    mission.target = "1.2.3.4"

    vote_result = MagicMock()
    vote_result.status = "approved"
    vote_result.escalation_reason = None

    consensus = AsyncMock()
    consensus.vote_on_action = AsyncMock(return_value=vote_result)

    result = await perform_consensus_check(mission, "nmap", "high", consensus)

    assert result is True
    mission.log.assert_any_call("[VOTE] High-risk action: nmap (high)")
    mission.log.assert_any_call("[APPROVED] Action validated by consensus")


@pytest.mark.asyncio
async def test_perform_consensus_check_rejected():
    mission = MagicMock()
    mission.log = MagicMock()
    mission.target = "1.2.3.4"

    vote_result = MagicMock()
    vote_result.status = "rejected"
    vote_result.escalation_reason = "too risky"

    consensus = AsyncMock()
    consensus.vote_on_action = AsyncMock(return_value=vote_result)

    result = await perform_consensus_check(mission, "sqlmap", "critical", consensus)

    assert result is False
    mission.log.assert_any_call("[REJECTED] Action blocked by consensus: too risky")
