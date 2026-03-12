"""Tests for agent context optimization, performance metrics, and error recovery."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.agents.base import Agent, AgentContext, AgentResult, AgentRole
from app.services.ai.agents.models import AgentAction
from app.services.ai.context import (
    AgentOutputCache,
    ContextManager,
    ContextSection,
    Priority,
    get_agent_cache,
    summarize_context,
)
from app.services.ai.errors import LLMParseError, LLMRateLimitError, LLMTimeoutError
from app.services.ai.llm import LLMResponse
from tests.mocks.llm import MockLLMClient

# ===== Context Summarization Tests =====


class TestSummarizeContext:
    def test_short_text_unchanged(self):
        text = "Short text"
        assert summarize_context(text, max_chars=1000) == text

    def test_empty_text(self):
        assert summarize_context("") == ""
        assert summarize_context(None) == None  # noqa: E711

    def test_long_text_compressed(self):
        """Long text should be meaningfully compressed, not just truncated."""
        lines = []
        for i in range(100):
            lines.append(f"Line {i}: some verbose filler content that goes on and on")
        text = "\n".join(lines)
        result = summarize_context(text, max_chars=500)
        assert len(result) <= 500

    def test_preserves_headings(self):
        text = "# Important Heading\n" + "filler " * 200 + "\n# Another Heading\nmore filler " * 100
        result = summarize_context(text, max_chars=300)
        assert "Important Heading" in result

    def test_preserves_bullet_points(self):
        lines = ["# Report"] + [f"- Finding {i}: critical vuln" for i in range(50)]
        text = "\n".join(lines)
        result = summarize_context(text, max_chars=400)
        assert "- Finding" in result

    def test_preserves_key_value_data(self):
        lines = ["Status: active", "Port: 443", "Service: https"] + ["verbose text " * 20] * 30
        text = "\n".join(lines)
        result = summarize_context(text, max_chars=300)
        assert ":" in result

    def test_adds_omission_marker(self):
        lines = [f"Line {i}" for i in range(200)]
        text = "\n".join(lines)
        result = summarize_context(text, max_chars=500)
        assert "summarized" in result or "truncated" in result


# ===== Agent Output Cache Tests =====


class TestAgentOutputCache:
    def test_basic_put_get(self):
        cache = AgentOutputCache(default_ttl=60.0)
        cache.put("agent_a", "prompt_1", {"result": "data"})
        assert cache.get("agent_a", "prompt_1") == {"result": "data"}

    def test_miss_on_different_prompt(self):
        cache = AgentOutputCache(default_ttl=60.0)
        cache.put("agent_a", "prompt_1", "value")
        assert cache.get("agent_a", "prompt_2") is None

    def test_miss_on_different_agent(self):
        cache = AgentOutputCache(default_ttl=60.0)
        cache.put("agent_a", "prompt_1", "value")
        assert cache.get("agent_b", "prompt_1") is None

    def test_expired_entry_returns_none(self):
        cache = AgentOutputCache(default_ttl=0.01)
        cache.put("agent_a", "prompt_1", "value")
        time.sleep(0.02)
        assert cache.get("agent_a", "prompt_1") is None

    def test_custom_ttl(self):
        cache = AgentOutputCache(default_ttl=0.01)
        cache.put("agent_a", "prompt_1", "value", ttl=60.0)
        time.sleep(0.02)
        assert cache.get("agent_a", "prompt_1") == "value"

    def test_eviction_at_max_capacity(self):
        cache = AgentOutputCache(default_ttl=60.0)
        # Fill to max
        for i in range(AgentOutputCache.MAX_ENTRIES):
            cache.put("a", f"p{i}", i)
        # One more should evict oldest
        cache.put("a", "overflow", "new")
        assert cache.get("a", "overflow") == "new"
        assert len(cache._store) <= AgentOutputCache.MAX_ENTRIES

    def test_clear(self):
        cache = AgentOutputCache(default_ttl=60.0)
        cache.put("a", "p", "v")
        cache.clear()
        assert cache.get("a", "p") is None

    def test_global_cache_singleton(self):
        c1 = get_agent_cache()
        c2 = get_agent_cache()
        assert c1 is c2


# ===== Agent Telemetry Integration Tests =====


class TestRecordAgentExecution:
    @pytest.mark.asyncio
    async def test_record_agent_execution_success(self):
        from app.core.telemetry import record_agent_execution, telemetry

        await record_agent_execution(
            agent_name="TestAgent",
            agent_role="parser",
            duration_ms=150.0,
            success=True,
            tokens=500,
        )
        # Counter should have been incremented
        found = any("agent_executions_total" in k for k in telemetry._counters)
        assert found

    @pytest.mark.asyncio
    async def test_record_agent_execution_failure(self):
        from app.core.telemetry import record_agent_execution, telemetry

        await record_agent_execution(
            agent_name="TestAgent",
            agent_role="parser",
            duration_ms=50.0,
            success=False,
        )
        found = any("agent_errors_total" in k for k in telemetry._counters)
        assert found

    @pytest.mark.asyncio
    async def test_record_iterations(self):
        from app.core.telemetry import record_agent_execution, telemetry

        await record_agent_execution(
            agent_name="TestAgent",
            agent_role="exploit_crafter",
            duration_ms=200.0,
            success=True,
            iterations=3,
        )
        found = any("agent_iterations" in k for k in telemetry._histograms)
        assert found


# ===== Agent Error Recovery / Retry Tests =====


class _DummyAction(AgentAction):
    action_type: str = "dummy"
    confidence: float = 0.9
    risk_level: str = "low"
    reasoning: str = "test"


class _DummyAgent(Agent):
    role = AgentRole.PARSER
    name = "DummyAgent"
    description = "test agent"

    async def execute(self, context, input_data):
        return AgentResult(success=True, action=_DummyAction())


class TestAgentRetryLogic:
    @pytest.fixture
    def agent(self):
        return _DummyAgent(MockLLMClient())

    @pytest.fixture
    def context(self):
        return AgentContext(mission_id="test", target="10.0.0.1", phase="discovery")

    @pytest.mark.asyncio
    async def test_successful_call_no_retry(self, agent):
        """Successful call should return immediately without retrying."""
        call_count = 0
        original_generate = agent.llm.generate

        async def counting_generate(**kwargs):
            nonlocal call_count
            call_count += 1
            return await original_generate(**kwargs)

        agent.llm.generate = counting_generate
        result = await agent._llm_generate(prompt="test")
        assert call_count == 1
        assert result.content == "Mock response"

    @pytest.mark.asyncio
    async def test_retry_on_timeout(self, agent):
        """TimeoutError should trigger retries then raise LLMTimeoutError."""
        agent.llm.generate = AsyncMock(side_effect=TimeoutError("timed out"))

        with pytest.raises(LLMTimeoutError):
            await agent._llm_generate(prompt="test")

        assert agent.llm.generate.call_count == 3

    @pytest.mark.asyncio
    async def test_retry_on_rate_limit(self, agent):
        """429 errors should trigger retries with longer backoff."""
        agent.llm.generate = AsyncMock(side_effect=Exception("429 Too Many Requests"))

        with pytest.raises(LLMRateLimitError):
            await agent._llm_generate(prompt="test")

        assert agent.llm.generate.call_count == 3

    @pytest.mark.asyncio
    async def test_retry_on_parse_error(self, agent):
        """JSON parse errors should be retried then raise LLMParseError."""
        agent.llm.generate = AsyncMock(side_effect=Exception("JSON parse error"))

        with pytest.raises(LLMParseError):
            await agent._llm_generate(prompt="test")

        assert agent.llm.generate.call_count == 3

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(self, agent):
        """If first call fails and second succeeds, return the success."""
        responses = [
            TimeoutError("timeout"),
            LLMResponse(content="success", model="mock", provider="mock", usage={}),
        ]
        call_idx = 0

        async def failing_then_success(**kwargs):
            nonlocal call_idx
            resp = responses[call_idx]
            call_idx += 1
            if isinstance(resp, Exception):
                raise resp
            return resp

        agent.llm.generate = failing_then_success
        result = await agent._llm_generate(prompt="test")
        assert result.content == "success"
        assert call_idx == 2

    @pytest.mark.asyncio
    async def test_cost_tracker_records_on_success(self, agent):
        """Cost tracker should record metrics on successful LLM call."""
        tracker = MagicMock()
        agent._cost_tracker = tracker

        await agent._llm_generate(prompt="test")

        tracker.record.assert_called_once()
        call_kwargs = tracker.record.call_args
        assert call_kwargs.kwargs["agent_name"] == "DummyAgent"

    @pytest.mark.asyncio
    async def test_structured_retry_on_validation_error(self, agent):
        """generate_structured parse failures should retry."""
        agent.llm.generate_structured = AsyncMock(side_effect=Exception("validation error: field required"))

        with pytest.raises(LLMParseError):
            await agent._llm_generate_structured(prompt="test", response_model=_DummyAction)

        assert agent.llm.generate_structured.call_count == 3


# ===== Execute with Telemetry Tests =====


class TestExecuteWithTelemetry:
    @pytest.mark.asyncio
    async def test_records_success_metrics(self):
        agent = _DummyAgent(MockLLMClient())
        context = AgentContext(mission_id="test", target="10.0.0.1", phase="discovery")

        with patch("app.core.telemetry.record_agent_execution", new_callable=AsyncMock) as mock_record:
            from pydantic import BaseModel

            class SimpleInput(BaseModel):
                data: str = "test"

            result = await agent.execute_with_telemetry(context, SimpleInput())

            assert result.success is True
            mock_record.assert_called_once()
            call_kwargs = mock_record.call_args.kwargs
            assert call_kwargs["agent_name"] == "DummyAgent"
            assert call_kwargs["success"] is True
            assert call_kwargs["duration_ms"] > 0


# ===== Context Manager Enhancement Tests =====


class TestContextManagerBuild:
    def test_medium_priority_dropped_before_high(self):
        ctx = ContextManager(max_context_tokens=20)  # ~80 chars
        sections = [
            ContextSection("critical", "A" * 40, Priority.CRITICAL),
            ContextSection("medium", "M" * 60, Priority.MEDIUM),
            ContextSection("high", "H" * 30, Priority.HIGH),
        ]
        result = ctx.build(sections)
        # Critical + High should fit; medium should be dropped
        assert "A" * 40 in result
        assert "M" * 60 not in result

    def test_optional_always_dropped_first(self):
        ctx = ContextManager(max_context_tokens=15)  # ~60 chars
        sections = [
            ContextSection("critical", "A" * 50, Priority.CRITICAL),
            ContextSection("optional", "O" * 50, Priority.OPTIONAL),
        ]
        result = ctx.build(sections)
        assert "A" * 50 in result
        assert "O" * 50 not in result
