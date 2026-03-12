"""Unit tests for ParserAgent (app/services/ai/agents/parser.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services.ai.agents.models import AgentContext, AgentRole
from app.services.ai.agents.parser import (
    ParsedFinding,
    ParserAgent,
    ParserInput,
    ParserOutput,
)
from tests.mocks.llm import MockLLMClient


def _make_context(**overrides) -> AgentContext:
    defaults = {
        "mission_id": "m-1",
        "target": "192.168.1.1",
        "phase": "discovery",
    }
    defaults.update(overrides)
    return AgentContext(**defaults)


class TestParserAgentRegistration:
    def test_role_is_parser(self):
        assert ParserAgent.role == AgentRole.PARSER

    def test_name(self):
        assert ParserAgent.name == "ParserAgent"


class TestParserAgentExecute:
    @pytest.mark.asyncio
    async def test_returns_parser_output_on_success(self):
        mock_output = ParserOutput(
            confidence=0.9,
            reasoning="Parsed nmap output",
            findings=[
                ParsedFinding(
                    type="port",
                    title="Open SSH",
                    severity="info",
                    confidence=0.9,
                    evidence="22/tcp open ssh",
                ),
            ],
            summary="Found SSH open",
            next_actions=["Run ssh-audit"],
        )
        llm = MockLLMClient(
            structured_responses={"ParserOutput": mock_output.model_dump()},
        )
        agent = ParserAgent(llm)
        ctx = _make_context()
        inp = ParserInput(
            tool_name="nmap",
            tool_output="22/tcp open ssh OpenSSH 8.9",
            target="192.168.1.1",
        )

        result = await agent.execute(ctx, inp)

        assert result.success is True
        assert result.action.findings[0].type == "port"
        assert result.metadata["findings_count"] == 1

    @pytest.mark.asyncio
    async def test_truncates_large_output(self):
        llm = MockLLMClient(
            structured_responses={
                "ParserOutput": ParserOutput(
                    findings=[],
                    summary="ok",
                    confidence=0.8,
                    reasoning="ok",
                ).model_dump(),
            },
        )
        agent = ParserAgent(llm)
        ctx = _make_context()
        inp = ParserInput(
            tool_name="nuclei",
            tool_output="x" * 20_000,
            target="example.com",
        )

        result = await agent.execute(ctx, inp)

        assert result.success is True
        # Verify the prompt sent to LLM was truncated
        last_call = llm.call_history[-1]
        assert len(last_call["prompt"]) < 20_000

    @pytest.mark.asyncio
    async def test_handles_llm_failure_gracefully(self):
        llm = MockLLMClient()
        # Make generate_structured raise
        llm.generate_structured = AsyncMock(side_effect=RuntimeError("LLM down"))
        agent = ParserAgent(llm)
        ctx = _make_context()
        inp = ParserInput(
            tool_name="nmap",
            tool_output="some output",
        )

        result = await agent.execute(ctx, inp)

        assert result.success is False
        assert "LLM down" in result.error

    @pytest.mark.asyncio
    async def test_default_target_from_context(self):
        llm = MockLLMClient(
            structured_responses={
                "ParserOutput": ParserOutput(
                    findings=[],
                    summary="ok",
                    confidence=0.8,
                    reasoning="ok",
                ).model_dump(),
            },
        )
        agent = ParserAgent(llm)
        ctx = _make_context(target="10.0.0.1")
        inp = ParserInput(
            tool_name="nmap",
            tool_output="output",
            target="",  # empty → should use context target
        )

        result = await agent.execute(ctx, inp)

        assert result.success is True
