"""Tests for LLM cost recording via telemetry and admin metrics aggregation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.telemetry import TelemetryCollector, record_llm_call

# ---------------------------------------------------------------------------
# record_llm_call
# ---------------------------------------------------------------------------


class TestRecordLlmCall:
    @pytest.mark.asyncio
    async def test_records_counters_and_histogram(self):
        collector = TelemetryCollector()
        with patch("app.core.telemetry.telemetry", collector):
            await record_llm_call(
                provider="openai",
                model="gpt-4o-mini",
                duration_ms=150.0,
                tokens=200,
                success=True,
            )

        summary = collector.get_metrics_summary()
        # Check counters were incremented
        calls_key = [k for k in summary["counters"] if k.startswith("llm_calls_total")]
        tokens_key = [k for k in summary["counters"] if k.startswith("llm_tokens_total")]
        assert len(calls_key) == 1
        assert summary["counters"][calls_key[0]] == 1
        assert summary["counters"][tokens_key[0]] == 200

    @pytest.mark.asyncio
    async def test_records_error_counter_on_failure(self):
        collector = TelemetryCollector()
        with patch("app.core.telemetry.telemetry", collector):
            await record_llm_call(
                provider="openai",
                model="gpt-4o",
                duration_ms=500.0,
                tokens=100,
                success=False,
            )

        summary = collector.get_metrics_summary()
        error_keys = [k for k in summary["counters"] if k.startswith("llm_errors_total")]
        assert len(error_keys) == 1
        assert summary["counters"][error_keys[0]] == 1

    @pytest.mark.asyncio
    async def test_no_error_counter_on_success(self):
        collector = TelemetryCollector()
        with patch("app.core.telemetry.telemetry", collector):
            await record_llm_call(
                provider="openai",
                model="gpt-4o",
                duration_ms=100.0,
                tokens=50,
                success=True,
            )

        summary = collector.get_metrics_summary()
        error_keys = [k for k in summary["counters"] if k.startswith("llm_errors_total")]
        assert len(error_keys) == 0

    @pytest.mark.asyncio
    async def test_labels_contain_provider_and_model(self):
        collector = TelemetryCollector()
        with patch("app.core.telemetry.telemetry", collector):
            await record_llm_call(
                provider="anthropic",
                model="claude-sonnet-4",
                duration_ms=200.0,
                tokens=300,
                success=True,
            )

        summary = collector.get_metrics_summary()
        # The key format is "name:provider=anthropic,model=claude-sonnet-4"
        calls_key = [k for k in summary["counters"] if "llm_calls_total" in k]
        assert any("provider=anthropic" in k and "model=claude-sonnet-4" in k for k in calls_key)

    @pytest.mark.asyncio
    async def test_multiple_calls_accumulate(self):
        collector = TelemetryCollector()
        with patch("app.core.telemetry.telemetry", collector):
            await record_llm_call("openai", "gpt-4o-mini", 100.0, 100, True)
            await record_llm_call("openai", "gpt-4o-mini", 200.0, 300, True)

        summary = collector.get_metrics_summary()
        tokens_key = [k for k in summary["counters"] if "llm_tokens_total" in k][0]
        assert summary["counters"][tokens_key] == 400


# ---------------------------------------------------------------------------
# TelemetryCollector — cost-relevant aggregation
# ---------------------------------------------------------------------------


class TestTelemetryCollectorCostMetrics:
    def test_increment_counter(self):
        tc = TelemetryCollector()
        tc.increment_counter("llm_calls_total", 1, {"provider": "openai"})
        tc.increment_counter("llm_calls_total", 1, {"provider": "openai"})

        summary = tc.get_metrics_summary()
        key = "llm_calls_total:provider=openai"
        assert summary["counters"][key] == 2

    def test_observe_histogram(self):
        tc = TelemetryCollector()
        tc.observe_histogram("llm_duration_ms", 100.0, {"model": "gpt-4o"})
        tc.observe_histogram("llm_duration_ms", 200.0, {"model": "gpt-4o"})

        summary = tc.get_metrics_summary()
        hist_key = "llm_duration_ms:model=gpt-4o"
        assert hist_key in summary["histograms"]
        stats = summary["histograms"][hist_key]
        assert stats["count"] == 2
        assert stats["min"] == 100.0
        assert stats["max"] == 200.0
        assert stats["avg"] == 150.0

    def test_set_gauge(self):
        tc = TelemetryCollector()
        tc.set_gauge("active_missions", 5.0)
        tc.set_gauge("active_missions", 3.0)

        summary = tc.get_metrics_summary()
        key = "active_missions:"
        assert summary["gauges"][key] == 3.0

    def test_adjust_gauge(self):
        tc = TelemetryCollector()
        tc.set_gauge("connections", 10.0)
        tc.adjust_gauge("connections", -3.0)

        summary = tc.get_metrics_summary()
        key = "connections:"
        assert summary["gauges"][key] == 7.0


# ---------------------------------------------------------------------------
# Admin metrics endpoint — cost data structure
# ---------------------------------------------------------------------------


class TestAdminMetricsEndpoint:
    @pytest.mark.asyncio
    async def test_returns_llm_cost_section(self):
        mock_collector = MagicMock()
        mock_collector.get_metrics_summary.return_value = {
            "counters": {
                "llm_calls_total:provider=openai,model=gpt-4o": 10,
                "llm_tokens_total:provider=openai,model=gpt-4o": 5000,
                "llm_errors_total:provider=openai,model=gpt-4o": 1,
            },
            "gauges": {},
            "histograms": {
                "llm_duration_ms:model=gpt-4o": {
                    "count": 10,
                    "min": 50,
                    "max": 500,
                    "avg": 200,
                    "p50": 180,
                    "p90": 400,
                    "p99": 500,
                }
            },
        }
        mock_collector.get_overview_stats.return_value = {
            "total_requests": 100,
            "total_errors": 2,
            "error_rate_percent": 2.0,
            "avg_latency_ms": 50.0,
            "latency_percentiles": {},
        }
        mock_collector.get_service_health.return_value = {}
        mock_collector.get_saas_metrics.return_value = {
            "active_users": 5,
            "missions": {"started": 3, "completed": 2},
            "latency_by_endpoint": {},
        }

        mock_store = MagicMock()
        mock_store.get_history.return_value = []

        with (
            patch("app.core.telemetry.telemetry", mock_collector),
            patch(
                "app.core.metrics_store.get_metrics_store",
                return_value=mock_store,
            ),
        ):
            from app.api.routers.admin.metrics import get_admin_metrics

            result = await get_admin_metrics(_user=MagicMock())

        assert "llm" in result
        assert result["llm"]["total_calls"] == 10
        assert result["llm"]["total_tokens"] == 5000
        assert result["llm"]["total_errors"] == 1
        assert result["llm"]["duration_stats"]["count"] == 10
