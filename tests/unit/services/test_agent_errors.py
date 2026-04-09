"""Tests for structured agent error types."""

from app.services.ai.errors import (
    AgentChainError,
    AgentError,
    LLMParseError,
    LLMRateLimitError,
    LLMTimeoutError,
)


class TestAgentError:
    def test_attributes(self):
        err = AgentError("boom", agent="recon", retryable=False)
        assert err.agent == "recon"
        assert err.retryable is False
        assert str(err) == "boom"

    def test_default_retryable_is_false(self):
        err = AgentError("msg", agent="a")
        assert err.retryable is False

    def test_is_exception(self):
        assert issubclass(AgentError, Exception)


class TestLLMTimeoutError:
    def test_is_retryable(self):
        err = LLMTimeoutError(agent="planner", timeout_seconds=30.0)
        assert err.retryable is True

    def test_preserves_timeout(self):
        err = LLMTimeoutError(agent="planner", timeout_seconds=45.5)
        assert err.timeout_seconds == 45.5

    def test_message_contains_seconds(self):
        err = LLMTimeoutError(agent="x", timeout_seconds=10.0)
        assert "10" in str(err)

    def test_inherits_agent_error(self):
        assert issubclass(LLMTimeoutError, AgentError)


class TestLLMParseError:
    def test_is_retryable(self):
        err = LLMParseError(agent="parser", raw_response="bad json")
        assert err.retryable is True

    def test_truncates_raw_response_to_500(self):
        long_response = "x" * 1000
        err = LLMParseError(agent="parser", raw_response=long_response)
        assert len(err.raw_response) == 500

    def test_short_response_not_truncated(self):
        err = LLMParseError(agent="parser", raw_response="short")
        assert err.raw_response == "short"

    def test_inherits_agent_error(self):
        assert issubclass(LLMParseError, AgentError)


class TestLLMRateLimitError:
    def test_is_retryable(self):
        err = LLMRateLimitError(agent="tool_selector")
        assert err.retryable is True

    def test_message(self):
        err = LLMRateLimitError(agent="tool_selector")
        assert "rate limit" in str(err).lower()

    def test_inherits_agent_error(self):
        assert issubclass(LLMRateLimitError, AgentError)


class TestAgentChainError:
    def test_preserves_cause(self):
        cause = ValueError("bad value")
        err = AgentChainError(agent="chain", step="step_2", cause=cause)
        assert err.cause is cause

    def test_preserves_step(self):
        err = AgentChainError(agent="chain", step="parse", cause=RuntimeError("x"))
        assert err.step == "parse"

    def test_not_retryable(self):
        err = AgentChainError(agent="chain", step="s", cause=Exception())
        assert err.retryable is False

    def test_message_contains_step_and_cause(self):
        err = AgentChainError(agent="chain", step="emit", cause=RuntimeError("oops"))
        msg = str(err)
        assert "emit" in msg
        assert "oops" in msg

    def test_inherits_agent_error(self):
        assert issubclass(AgentChainError, AgentError)


class TestAllErrorsInheritAgentError:
    def test_all_inherit(self):
        for cls in (LLMTimeoutError, LLMParseError, LLMRateLimitError, AgentChainError):
            assert issubclass(cls, AgentError), f"{cls.__name__} does not inherit AgentError"
