"""Unit tests for ScopeAgent — host budget and regex extraction (no LLM)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from spectra_ai_core.agents.base import AgentContext
from spectra_ai_core.agents.scope import ScopeAgent, ScopeInput
from tests.mocks.llm import MockLLMClient


@pytest.mark.asyncio
async def test_scope_agent_warns_when_validated_host_count_exceeds_max_hosts():
    """CIDR host cardinality can exceed max_hosts; agent records a warning and caps total_hosts."""
    ctx = AgentContext(mission_id="m-test")
    agent = ScopeAgent(MockLLMClient())
    with patch.object(ScopeAgent, "_parse_with_llm", new=AsyncMock()):
        result = await agent.execute(
            ctx,
            ScopeInput(raw_input="10.0.0.0/24", max_hosts=10),
        )

    assert result.success
    assert result.action is not None
    warnings = result.action.warnings
    assert any("Scope exceeds max hosts" in w for w in warnings)
    assert result.action.total_hosts == 10


@pytest.mark.asyncio
async def test_scope_agent_single_ip_respects_max_hosts_without_warning():
    ctx = AgentContext(mission_id="m-test")
    agent = ScopeAgent(MockLLMClient())
    with patch.object(ScopeAgent, "_parse_with_llm", new=AsyncMock()):
        result = await agent.execute(
            ctx,
            ScopeInput(raw_input="192.168.1.50", max_hosts=50),
        )

    assert result.success
    assert result.action is not None
    assert not any("Scope exceeds max hosts" in w for w in result.action.warnings)
    assert result.action.total_hosts == 1
