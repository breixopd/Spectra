"""Tests for per-agent LLM cost tracking."""

from spectra_ai_core.cost_tracker import AgentUsage, CostTracker


def _usage(prompt: int = 100, completion: int = 50, total: int | None = None) -> dict[str, int]:
    d: dict[str, int] = {"prompt_tokens": prompt, "completion_tokens": completion}
    if total is not None:
        d["total_tokens"] = total
    return d


# ---------------------------------------------------------------------------


def test_record_basic_usage():
    """Record a call, check fields."""
    ct = CostTracker("m1")
    ct.record("ScopeAgent", "scope", "gpt-4o-mini", _usage())

    entry = ct.get_agent_usage("ScopeAgent")
    assert entry is not None
    assert entry.calls == 1
    assert entry.input_tokens == 100
    assert entry.output_tokens == 50
    assert entry.total_tokens == 150
    assert entry.role == "scope"


def test_record_multiple_calls():
    """Aggregate calls for the same agent."""
    ct = CostTracker("m2")
    ct.record("ScopeAgent", "scope", "gpt-4o-mini", _usage(100, 50))
    ct.record("ScopeAgent", "scope", "gpt-4o-mini", _usage(200, 100))

    entry = ct.get_agent_usage("ScopeAgent")
    assert entry is not None
    assert entry.calls == 2
    assert entry.input_tokens == 300
    assert entry.output_tokens == 150
    assert entry.total_tokens == 450


def test_record_multiple_agents():
    """Separate tracking per agent."""
    ct = CostTracker("m3")
    ct.record("Agent-A", "scope", "gpt-4o-mini", _usage(10, 5))
    ct.record("Agent-B", "parser", "gpt-4o-mini", _usage(20, 10))

    usage_a = ct.get_agent_usage("Agent-A")
    usage_b = ct.get_agent_usage("Agent-B")
    assert usage_a is not None
    assert usage_b is not None
    assert usage_a.calls == 1
    assert usage_b.calls == 1


def test_cost_estimation_known_model():
    """Verify cost calculation for gpt-4o-mini."""
    ct = CostTracker("m4")
    # gpt-4o-mini: input $0.15/1M, output $0.60/1M
    ct.record("A", "scope", "gpt-4o-mini", _usage(1_000_000, 1_000_000))

    entry = ct.get_agent_usage("A")
    assert entry is not None
    expected = 0.15 + 0.60  # $0.75
    assert abs(entry.estimated_cost_usd - expected) < 1e-6


def test_cost_estimation_unknown_model():
    """Unknown models return 0.0 cost."""
    ct = CostTracker("m5")
    ct.record("A", "scope", "totally-unknown-model-xyz", _usage(1_000_000, 1_000_000))

    entry = ct.get_agent_usage("A")
    assert entry is not None
    assert entry.estimated_cost_usd == 0.0


def test_cost_estimation_ollama_free():
    """Local Ollama models have 0 cost."""
    ct = CostTracker("m6")
    ct.record("A", "scope", "ollama/llama3", _usage(500_000, 500_000))

    entry = ct.get_agent_usage("A")
    assert entry is not None
    assert entry.estimated_cost_usd == 0.0


def test_get_summary():
    """Verify summary structure and totals."""
    ct = CostTracker("m7")
    ct.record("A", "scope", "gpt-4o-mini", _usage(100, 50))
    ct.record("B", "parser", "gpt-4o-mini", _usage(200, 100))

    summary = ct.get_summary()
    assert summary["mission_id"] == "m7"
    assert summary["total_tokens"] == 450
    assert summary["total_calls"] == 2
    assert "by_agent" in summary
    assert "A" in summary["by_agent"]
    assert "B" in summary["by_agent"]
    assert summary["total_cost_usd"] >= 0
    assert "duration_seconds" in summary


def test_get_agent_usage():
    """Returns correct AgentUsage or None."""
    ct = CostTracker("m8")
    assert ct.get_agent_usage("missing") is None

    ct.record("X", "scope", "gpt-4o-mini", _usage())
    result = ct.get_agent_usage("X")
    assert isinstance(result, AgentUsage)
    assert result.agent_name == "X"


def test_latency_tracking():
    """avg_latency_ms calculated correctly."""
    ct = CostTracker("m9")
    ct.record("A", "scope", "gpt-4o-mini", _usage(), latency_ms=100.0)
    ct.record("A", "scope", "gpt-4o-mini", _usage(), latency_ms=200.0)
    ct.record("A", "scope", "gpt-4o-mini", _usage(), latency_ms=300.0)

    entry = ct.get_agent_usage("A")
    assert entry is not None
    assert abs(entry.avg_latency_ms - 200.0) < 1e-6


def test_error_counting():
    """Error flag increments errors."""
    ct = CostTracker("m10")
    ct.record("A", "scope", "gpt-4o-mini", _usage(), error=True)
    ct.record("A", "scope", "gpt-4o-mini", _usage(), error=False)
    ct.record("A", "scope", "gpt-4o-mini", _usage(), error=True)

    entry = ct.get_agent_usage("A")
    assert entry is not None
    assert entry.errors == 2
    assert entry.calls == 3
