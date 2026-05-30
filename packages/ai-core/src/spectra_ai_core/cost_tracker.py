"""Per-agent, per-mission LLM cost tracking."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Global registry of active cost trackers keyed by mission_id
_cost_trackers: dict[str, CostTracker] = {}


def get_cost_trackers() -> dict[str, CostTracker]:
    """Return the global registry of active cost trackers."""
    return _cost_trackers


# List pricing per 1M tokens (cache-miss input, output) for the only models the platform
# uses — DeepSeek V4 via TensorZero. Permanent list rates (the v4-pro launch promo expires
# 2026-05-31); cache-hit input is far cheaper but is not separately metered here, so these
# rates are a conservative upper bound. Source: api-docs.deepseek.com/quick_start/pricing.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # (input_per_1M, output_per_1M)
    "deepseek-v4-flash": (0.14, 0.28),
    "deepseek-v4-pro": (1.74, 3.48),
}

# Pre-sorted by prefix length descending so "deepseek-v4-flash" matches before any
# shorter alias.
_SORTED_MODEL_PRICING: list[tuple[str, tuple[float, float]]] = sorted(
    MODEL_PRICING.items(), key=lambda kv: len(kv[0]), reverse=True
)


@dataclass
class AgentUsage:
    """Token usage by a single agent."""

    agent_name: str
    role: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    errors: int = 0
    avg_latency_ms: float = 0.0
    _latency_sum: float = 0.0
    _latencies: list[float] = field(default_factory=list, repr=False)


class CostTracker:
    """Tracks LLM costs and token usage per agent per mission."""

    def __init__(self, mission_id: str):
        self.mission_id = mission_id
        self._usage: dict[str, AgentUsage] = {}
        self._start_time = time.monotonic()

    def record(
        self,
        agent_name: str,
        agent_role: str,
        model: str,
        usage: dict[str, int],
        latency_ms: float = 0.0,
        error: bool = False,
    ) -> None:
        """Record a single LLM call's usage."""
        if agent_name not in self._usage:
            self._usage[agent_name] = AgentUsage(agent_name=agent_name, role=agent_role)

        entry = self._usage[agent_name]
        entry.calls += 1

        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        total = usage.get("total_tokens", input_tokens + output_tokens)

        entry.input_tokens += input_tokens
        entry.output_tokens += output_tokens
        entry.total_tokens += total

        if error:
            entry.errors += 1

        if latency_ms > 0:
            entry._latencies.append(latency_ms)
            entry._latency_sum += latency_ms
            entry.avg_latency_ms = entry._latency_sum / len(entry._latencies)

        entry.estimated_cost_usd += self._estimate_cost(model, input_tokens, output_tokens)

    def _estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost based on model pricing."""
        model_lower = model.lower()
        for prefix, (input_price, output_price) in _SORTED_MODEL_PRICING:
            if prefix in model_lower:
                return (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price
        return 0.0  # Unknown model, assume free

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of all usage."""
        total_cost = sum(u.estimated_cost_usd for u in self._usage.values())
        total_tokens = sum(u.total_tokens for u in self._usage.values())
        total_calls = sum(u.calls for u in self._usage.values())

        return {
            "mission_id": self.mission_id,
            "total_cost_usd": round(total_cost, 6),
            "total_tokens": total_tokens,
            "total_calls": total_calls,
            "duration_seconds": round(time.monotonic() - self._start_time, 1),
            "by_agent": {
                name: {
                    "role": u.role,
                    "calls": u.calls,
                    "tokens": u.total_tokens,
                    "cost_usd": round(u.estimated_cost_usd, 6),
                    "errors": u.errors,
                    "avg_latency_ms": round(u.avg_latency_ms, 1),
                }
                for name, u in self._usage.items()
            },
        }

    def register(self) -> None:
        """Register this tracker in the global registry."""
        _cost_trackers[self.mission_id] = self

    def unregister(self) -> None:
        """Remove this tracker from the global registry."""
        _cost_trackers.pop(self.mission_id, None)

    def get_agent_usage(self, agent_name: str) -> AgentUsage | None:
        """Get usage for a specific agent."""
        return self._usage.get(agent_name)
