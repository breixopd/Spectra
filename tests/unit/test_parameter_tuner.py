"""Unit tests for ParameterTunerAgent (app/services/ai/agents/parameter_tuner.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services.ai.agents.models import AgentContext, AgentRole
from app.services.ai.agents.parameter_tuner import (
    COMPLEX_TOOLS,
    TOOL_KNOWLEDGE,
    ParameterTunerAgent,
    TunerInput,
    TunerOutput,
)
from tests.mocks.llm import MockLLMClient


def _make_context(**overrides) -> AgentContext:
    defaults = {
        "mission_id": "m-1",
        "target": "10.0.0.1",
        "phase": "discovery",
    }
    defaults.update(overrides)
    return AgentContext(**defaults)


class TestParameterTunerRegistration:
    def test_role_is_parameter_tuner(self):
        assert ParameterTunerAgent.role == AgentRole.PARAMETER_TUNER

    def test_name(self):
        assert ParameterTunerAgent.name == "ParameterTunerAgent"


class TestIsComplexTool:
    def test_known_complex_tools(self):
        for tool in ["nmap", "nuclei", "gobuster", "sqlmap", "hydra"]:
            assert ParameterTunerAgent.is_complex_tool(tool) is True

    def test_case_insensitive(self):
        assert ParameterTunerAgent.is_complex_tool("NMAP") is True

    def test_unknown_tool_not_complex(self):
        assert ParameterTunerAgent.is_complex_tool("my_custom_tool") is False


class TestParameterTunerExecute:
    @pytest.mark.asyncio
    async def test_known_tool_returns_tuner_output(self):
        mock_output = TunerOutput(
            confidence=0.9,
            reasoning="Standard nmap discovery",
            tool_args={"-sV": True, "-p": "1-1000"},
            timeout=600,
            notes="Version detection on top 1000 ports",
        )
        llm = MockLLMClient(
            structured_responses={"TunerOutput": mock_output.model_dump()},
        )
        agent = ParameterTunerAgent(llm)
        ctx = _make_context()
        inp = TunerInput(
            tool_name="nmap",
            target="10.0.0.1",
            target_type="ip",
            phase="discovery",
        )

        result = await agent.execute(ctx, inp)

        assert result.success is True
        assert result.action.tool_args["-sV"] is True
        assert result.action.timeout == 600

    @pytest.mark.asyncio
    async def test_unknown_tool_still_returns_output(self):
        mock_output = TunerOutput(
            confidence=0.7,
            reasoning="Unknown tool, basic params",
            tool_args={"--target": "10.0.0.1"},
            timeout=300,
            notes="Basic parameters",
        )
        llm = MockLLMClient(
            structured_responses={"TunerOutput": mock_output.model_dump()},
        )
        agent = ParameterTunerAgent(llm)
        ctx = _make_context()
        inp = TunerInput(
            tool_name="unknown_scanner",
            target="10.0.0.1",
            target_type="ip",
            phase="discovery",
        )

        result = await agent.execute(ctx, inp)

        assert result.success is True
        assert isinstance(result.action.tool_args, dict)

    @pytest.mark.asyncio
    async def test_stealth_mode_included_in_prompt(self):
        llm = MockLLMClient(
            structured_responses={
                "TunerOutput": TunerOutput(
                    tool_args={}, timeout=300, confidence=0.8, reasoning="ok",
                ).model_dump(),
            },
        )
        agent = ParameterTunerAgent(llm)
        ctx = _make_context()
        inp = TunerInput(
            tool_name="nmap",
            target="10.0.0.1",
            stealth_mode=True,
        )

        await agent.execute(ctx, inp)

        last_prompt = llm.call_history[-1]["prompt"]
        assert "Yes" in last_prompt  # stealth_mode formatted as "Yes"

    @pytest.mark.asyncio
    async def test_previous_results_summarized(self):
        llm = MockLLMClient(
            structured_responses={
                "TunerOutput": TunerOutput(
                    tool_args={}, timeout=300, confidence=0.8, reasoning="ok",
                ).model_dump(),
            },
        )
        agent = ParameterTunerAgent(llm)
        ctx = _make_context()
        inp = TunerInput(
            tool_name="nuclei",
            target="example.com",
            previous_results=[
                {"tool": "nmap", "findings_count": 5},
                {"tool": "subfinder", "findings_count": 12},
            ],
        )

        await agent.execute(ctx, inp)

        last_prompt = llm.call_history[-1]["prompt"]
        assert "nmap" in last_prompt
        assert "5 findings" in last_prompt

    @pytest.mark.asyncio
    async def test_handles_llm_failure(self):
        llm = MockLLMClient()
        llm.generate_structured = AsyncMock(side_effect=RuntimeError("timeout"))
        agent = ParameterTunerAgent(llm)
        ctx = _make_context()
        inp = TunerInput(tool_name="nmap", target="10.0.0.1")

        result = await agent.execute(ctx, inp)

        assert result.success is False
        assert "timeout" in result.error

    def test_tool_knowledge_keys_subset_of_complex(self):
        """All tools with domain knowledge should be in COMPLEX_TOOLS."""
        for tool in TOOL_KNOWLEDGE:
            assert tool in COMPLEX_TOOLS
