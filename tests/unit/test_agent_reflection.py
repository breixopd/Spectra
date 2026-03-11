"""Tests for Agent reflection/self-critique loop."""

import json
from typing import Any, ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from app.services.ai.agents.base import (
    Agent,
    AgentAction,
    AgentContext,
    AgentResult,
    AgentRole,
)

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _Input(BaseModel):
    value: str = "test"


class _Output(AgentAction):
    action_type: str = "test"
    confidence: float = 0.9
    risk_level: str = "low"
    reasoning: str = "good"


def _ctx(**overrides: Any) -> AgentContext:
    defaults: dict[str, Any] = {
        "mission_id": "m-1",
        "target": "10.0.0.1",
        "phase": "discovery",
    }
    defaults.update(overrides)
    return AgentContext(**defaults)


def _make_agent(
    *,
    enable_reflection: bool = False,
    threshold: float = 0.7,
    execute_results: list[AgentResult] | None = None,
) -> Agent[Any, Any]:
    """Build a concrete agent with a controllable execute()."""

    class _Ag(Agent[_Input, _Output]):
        role: ClassVar[AgentRole] = AgentRole.SCOPE  # type: ignore[assignment]
        name: ClassVar[str] = "ReflTest"
        description: ClassVar[str] = "reflection test agent"
        enable_reflection: ClassVar[bool] = enable_reflection  # type: ignore[assignment]
        reflection_threshold: ClassVar[float] = threshold  # type: ignore[assignment]

        async def execute(self, context: AgentContext, input_data: _Input) -> AgentResult:
            ...  # replaced by mock

    ag = _Ag(MagicMock())

    results = execute_results or [AgentResult(success=True, action=_Output())]
    ag.execute = AsyncMock(side_effect=results)  # type: ignore[method-assign]
    return ag


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.services.ai.agents.base.events")
async def test_reflection_disabled_skips(mock_events: MagicMock):
    """When enable_reflection=False, execute_with_reflection just calls execute."""
    agent = _make_agent(enable_reflection=False)
    result = await agent.execute_with_reflection(_ctx(), _Input())

    assert result.success
    agent.execute.assert_awaited_once()


@pytest.mark.asyncio
@patch("app.services.ai.agents.base.events")
async def test_reflection_high_quality_accepts(mock_events: MagicMock):
    """Quality > threshold returns immediately without retry."""
    agent = _make_agent(enable_reflection=True, threshold=0.7)

    reflect_response = MagicMock()
    reflect_response.content = json.dumps({"quality": 0.95, "feedback": "great"})
    reflect_response.model = "test"
    reflect_response.usage = {"prompt_tokens": 10, "completion_tokens": 5}

    agent._llm_generate = AsyncMock(return_value=reflect_response)

    result = await agent.execute_with_reflection(_ctx(), _Input())
    assert result.success
    # Only one execute call — no retry when quality is high
    assert agent.execute.await_count == 1


@pytest.mark.asyncio
@patch("app.services.ai.agents.base.events")
async def test_reflection_low_quality_retries(mock_events: MagicMock):
    """Quality < threshold causes retry with feedback."""
    r1 = AgentResult(success=True, action=_Output(reasoning="first"))
    r2 = AgentResult(success=True, action=_Output(reasoning="second"))
    agent = _make_agent(enable_reflection=True, threshold=0.9, execute_results=[r1, r2])

    low_resp = MagicMock()
    low_resp.content = json.dumps({"quality": 0.5, "feedback": "needs improvement"})
    low_resp.model = "test"
    low_resp.usage = {"prompt_tokens": 10, "completion_tokens": 5}

    high_resp = MagicMock()
    high_resp.content = json.dumps({"quality": 0.95, "feedback": "much better"})
    high_resp.model = "test"
    high_resp.usage = {"prompt_tokens": 10, "completion_tokens": 5}

    agent._llm_generate = AsyncMock(side_effect=[low_resp, high_resp])

    result = await agent.execute_with_reflection(_ctx(), _Input(), max_iterations=2)
    assert result.success
    assert agent.execute.await_count == 2


@pytest.mark.asyncio
@patch("app.services.ai.agents.base.events")
async def test_reflection_failure_returns_default_score(mock_events: MagicMock):
    """If reflection LLM fails, returns 0.8 default quality."""
    agent = _make_agent(enable_reflection=True, threshold=0.7)

    # Simulate _reflect raising an exception internally → returns (0.8, "")
    agent._llm_generate = AsyncMock(side_effect=Exception("LLM down"))

    result = await agent.execute_with_reflection(_ctx(), _Input())
    # 0.8 >= 0.7 threshold, so should accept on first iteration
    assert result.success
    assert agent.execute.await_count == 1


@pytest.mark.asyncio
@patch("app.services.ai.agents.base.events")
async def test_reflection_max_iterations(mock_events: MagicMock):
    """Stops after max_iterations."""
    results = [
        AgentResult(success=True, action=_Output(reasoning=f"attempt-{i}"))
        for i in range(5)
    ]
    agent = _make_agent(enable_reflection=True, threshold=0.99, execute_results=results)

    low_resp = MagicMock()
    low_resp.content = json.dumps({"quality": 0.3, "feedback": "still bad"})
    low_resp.model = "test"
    low_resp.usage = {"prompt_tokens": 10, "completion_tokens": 5}

    agent._llm_generate = AsyncMock(return_value=low_resp)

    result = await agent.execute_with_reflection(_ctx(), _Input(), max_iterations=3)
    assert result.success
    # Capped at max_iterations
    assert agent.execute.await_count == 3


def test_reflection_enabled_on_exploit_crafter():
    """Verify ExploitCrafter.enable_reflection is True."""
    from app.services.ai.agents.exploit_crafter import ExploitCrafterAgent

    assert ExploitCrafterAgent.enable_reflection is True
