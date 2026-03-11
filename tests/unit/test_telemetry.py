"""Tests for app.core.telemetry module."""

from unittest.mock import patch

import pytest

from app.core.telemetry import TelemetryCollector, record_llm_call


@pytest.fixture
def collector():
    """Return a fresh TelemetryCollector for each test."""
    return TelemetryCollector()


class TestIncrementCounter:
    def test_basic_increment(self, collector):
        collector.increment_counter("requests", 1)
        summary = collector.get_metrics_summary()
        assert (
            "requests:" in list(summary["counters"].keys())[0]
            or summary["counters"].get("requests:") == 1
        )

    def test_increment_with_labels(self, collector):
        collector.increment_counter("http_requests", 1, {"method": "GET"})
        summary = collector.get_metrics_summary()
        key = "http_requests:method=GET"
        assert summary["counters"][key] == 1

    def test_multiple_increments_accumulate(self, collector):
        collector.increment_counter("hits", 3, {"path": "/api"})
        collector.increment_counter("hits", 7, {"path": "/api"})
        summary = collector.get_metrics_summary()
        key = "hits:path=/api"
        assert summary["counters"][key] == 10


class TestRecordHistogram:
    def test_single_observation(self, collector):
        collector.observe_histogram("latency", 42.5)
        summary = collector.get_metrics_summary()
        key = "latency:"
        assert key in summary["histograms"]
        assert summary["histograms"][key]["count"] == 1
        assert summary["histograms"][key]["min"] == 42.5
        assert summary["histograms"][key]["max"] == 42.5

    def test_multiple_observations(self, collector):
        for v in [10, 20, 30, 40, 50]:
            collector.observe_histogram("duration", v)
        summary = collector.get_metrics_summary()
        key = "duration:"
        stats = summary["histograms"][key]
        assert stats["count"] == 5
        assert stats["min"] == 10
        assert stats["max"] == 50
        assert stats["avg"] == 30.0

    def test_histogram_with_labels(self, collector):
        collector.observe_histogram("rtt", 100.0, {"region": "us-east"})
        summary = collector.get_metrics_summary()
        key = "rtt:region=us-east"
        assert key in summary["histograms"]


class TestServiceStatus:
    def test_healthy_service(self, collector):
        collector.update_service_status("db", healthy=True, latency_ms=5.0)
        statuses = collector.get_service_health()
        assert "db" in statuses
        assert statuses["db"]["healthy"] is True
        assert statuses["db"]["latency_ms"] == 5.0
        assert statuses["db"]["error"] is None

    def test_unhealthy_service_with_error(self, collector):
        collector.update_service_status(
            "cache", healthy=False, error="connection refused"
        )
        statuses = collector.get_service_health()
        assert statuses["cache"]["healthy"] is False
        assert statuses["cache"]["error"] == "connection refused"

    def test_service_status_updates_overwrite(self, collector):
        collector.update_service_status("api", healthy=True, latency_ms=10.0)
        collector.update_service_status(
            "api", healthy=False, latency_ms=999.0, error="timeout"
        )
        statuses = collector.get_service_health()
        assert statuses["api"]["healthy"] is False
        assert statuses["api"]["latency_ms"] == 999.0


class TestGetStats:
    def test_empty_stats_structure(self, collector):
        summary = collector.get_metrics_summary()
        assert "counters" in summary
        assert "gauges" in summary
        assert "histograms" in summary
        assert isinstance(summary["counters"], dict)
        assert isinstance(summary["gauges"], dict)
        assert isinstance(summary["histograms"], dict)

    def test_overview_stats_defaults(self, collector):
        overview = collector.get_overview_stats()
        assert overview["total_requests"] == 0
        assert overview["total_errors"] == 0
        assert overview["error_rate_percent"] == 0
        assert overview["avg_latency_ms"] == 0

    def test_overview_counts_healthy_services(self, collector):
        collector.update_service_status("svc1", healthy=True)
        collector.update_service_status("svc2", healthy=False)
        collector.update_service_status("svc3", healthy=True)
        overview = collector.get_overview_stats()
        assert overview["active_services"] == 3
        assert overview["healthy_services"] == 2


class TestLatencyPercentiles:
    def test_percentiles_from_traces(self, collector):
        trace_id = collector.create_trace()
        values = list(range(1, 101))
        for v in values:
            span = collector.start_span("op", trace_id=trace_id)
            span.duration_ms = float(v)
            span.end_time = span.start_time
            collector._traces.append(span)
            collector._request_count += 1
            collector._total_latency += float(v)

        overview = collector.get_overview_stats()
        assert "p50_ms" in overview["latency_percentiles"]
        assert "p90_ms" in overview["latency_percentiles"]
        assert "p99_ms" in overview["latency_percentiles"]

    def test_histogram_percentiles(self, collector):
        for v in range(1, 101):
            collector.observe_histogram("resp_time", float(v))
        summary = collector.get_metrics_summary()
        stats = summary["histograms"]["resp_time:"]
        assert stats["p50"] == 51
        assert stats["p90"] == 91
        assert stats["p99"] == 100


class TestRecordLLMCall:
    @pytest.mark.asyncio
    async def test_successful_call(self):
        fresh = TelemetryCollector()
        with patch("app.core.telemetry.telemetry", fresh):
            await record_llm_call("openai", "gpt-4", 150.0, 500, success=True)
        summary = fresh.get_metrics_summary()
        assert summary["counters"]["llm_calls_total:model=gpt-4,provider=openai"] == 1
        assert (
            summary["counters"]["llm_tokens_total:model=gpt-4,provider=openai"] == 500
        )
        assert "llm_errors_total:model=gpt-4,provider=openai" not in summary["counters"]

    @pytest.mark.asyncio
    async def test_failed_call_records_error(self):
        fresh = TelemetryCollector()
        with patch("app.core.telemetry.telemetry", fresh):
            await record_llm_call("anthropic", "claude", 200.0, 0, success=False)
        summary = fresh.get_metrics_summary()
        assert (
            summary["counters"]["llm_errors_total:model=claude,provider=anthropic"] == 1
        )
