"""Tests for OTLP export and SaaS metrics in app.core.telemetry."""

import pytest

from app.core.telemetry import TelemetryCollector


@pytest.fixture
def collector():
    return TelemetryCollector()


# ---------------------------------------------------------------------------
# export_otlp_format
# ---------------------------------------------------------------------------


class TestExportOtlpFormat:
    def test_empty_collector_returns_valid_structure(self, collector):
        result = collector.export_otlp_format()
        assert "resourceMetrics" in result
        assert "resourceSpans" in result
        assert len(result["resourceMetrics"]) == 1
        assert len(result["resourceSpans"]) == 1

    def test_resource_attributes(self, collector):
        result = collector.export_otlp_format()
        resource = result["resourceMetrics"][0]["resource"]
        attr_keys = [a["key"] for a in resource["attributes"]]
        assert "service.name" in attr_keys
        assert "service.version" in attr_keys
        assert "telemetry.sdk.language" in attr_keys

        name_attr = next(a for a in resource["attributes"] if a["key"] == "service.name")
        assert name_attr["value"]["stringValue"] == "spectra"

    def test_scope_metrics_structure(self, collector):
        result = collector.export_otlp_format()
        scope_metrics = result["resourceMetrics"][0]["scopeMetrics"]
        assert len(scope_metrics) == 1
        assert scope_metrics[0]["scope"]["name"] == "spectra.telemetry"
        assert isinstance(scope_metrics[0]["metrics"], list)

    def test_scope_spans_structure(self, collector):
        result = collector.export_otlp_format()
        scope_spans = result["resourceSpans"][0]["scopeSpans"]
        assert len(scope_spans) == 1
        assert scope_spans[0]["scope"]["name"] == "spectra.telemetry"
        assert isinstance(scope_spans[0]["spans"], list)

    def test_counter_exported_as_sum(self, collector):
        collector.increment_counter("http.requests", 42, {"method": "GET"})
        result = collector.export_otlp_format()
        metrics = result["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
        names = [m["name"] for m in metrics]
        assert "http.requests" in names
        metric = next(m for m in metrics if m["name"] == "http.requests")
        dp = metric["sum"]["dataPoints"][0]
        assert dp["asDouble"] == 42
        assert dp["isMonotonic"] is True
        assert dp["aggregationTemporality"] == 2

    def test_histogram_exported(self, collector):
        for v in [10.0, 20.0, 30.0]:
            collector.observe_histogram("latency", v)
        result = collector.export_otlp_format()
        metrics = result["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
        hist = next(m for m in metrics if m["name"] == "latency")
        dp = hist["histogram"]["dataPoints"][0]
        assert dp["count"] == "3"
        assert dp["sum"] == 60.0
        assert dp["min"] == 10.0
        assert dp["max"] == 30.0

    def test_spans_exported_for_completed_traces(self, collector):
        span = collector.start_span("test.op", attributes={"key": "val"})
        collector.end_span(span, "ok")
        result = collector.export_otlp_format()
        spans = result["resourceSpans"][0]["scopeSpans"][0]["spans"]
        assert len(spans) == 1
        s = spans[0]
        assert s["traceId"] == span.trace_id
        assert s["spanId"] == span.span_id
        assert s["name"] == "test.op"
        assert s["kind"] == 1  # INTERNAL
        assert s["status"]["code"] == 1  # OK

    def test_error_span_status_code(self, collector):
        span = collector.start_span("fail.op")
        collector.end_span(span, "error", "boom")
        result = collector.export_otlp_format()
        spans = result["resourceSpans"][0]["scopeSpans"][0]["spans"]
        assert spans[0]["status"]["code"] == 2  # ERROR

    def test_parent_span_id_included(self, collector):
        trace_id = collector.create_trace()
        parent = collector.start_span("parent", trace_id=trace_id)
        collector.end_span(parent)
        child = collector.start_span("child", trace_id=trace_id, parent_id=parent.span_id)
        collector.end_span(child)
        result = collector.export_otlp_format()
        spans = result["resourceSpans"][0]["scopeSpans"][0]["spans"]
        child_span = next(s for s in spans if s["name"] == "child")
        assert child_span["parentSpanId"] == parent.span_id

    def test_span_attributes_serialized(self, collector):
        span = collector.start_span("attr.op", attributes={"http.method": "POST", "code": 200})
        collector.end_span(span)
        result = collector.export_otlp_format()
        s = result["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attr_keys = [a["key"] for a in s["attributes"]]
        assert "http.method" in attr_keys
        assert "code" in attr_keys

    def test_time_fields_are_nanosecond_strings(self, collector):
        span = collector.start_span("time.op")
        collector.end_span(span)
        result = collector.export_otlp_format()
        s = result["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        assert isinstance(s["startTimeUnixNano"], str)
        assert isinstance(s["endTimeUnixNano"], str)
        assert int(s["startTimeUnixNano"]) > 0


# ---------------------------------------------------------------------------
# get_saas_metrics
# ---------------------------------------------------------------------------


class TestGetSaasMetrics:
    def test_empty_returns_zero_defaults(self, collector):
        result = collector.get_saas_metrics()
        assert result["active_users"] == 0
        assert result["missions"]["started"] == 0
        assert result["missions"]["completed"] == 0
        assert result["api_error_rates"] == {}
        assert result["latency_by_endpoint"] == {}

    def test_active_users_from_auth_counters(self, collector):
        collector.increment_counter("auth.login", 5)
        collector.increment_counter("auth.token_refresh", 3)
        result = collector.get_saas_metrics()
        assert result["active_users"] == 8

    def test_mission_throughput(self, collector):
        collector.increment_counter("mission_events_total", 10, {"event": "started"})
        collector.increment_counter("mission_events_total", 7, {"event": "completed"})
        result = collector.get_saas_metrics()
        assert result["missions"]["started"] == 10
        assert result["missions"]["completed"] == 7

    def test_api_error_rates_by_path(self, collector):
        # The key format is "name:label1=v1,label2=v2" (sorted).
        # get_saas_metrics splits on "," and looks for parts starting with "path=".
        # "path" must not be the first label (it gets prefixed with "name:").
        collector.increment_counter("http.requests.errors", 3, {"method": "GET", "path": "/api/missions"})
        collector.increment_counter("http.requests.errors", 1, {"method": "POST", "path": "/api/targets"})
        result = collector.get_saas_metrics()
        assert result["api_error_rates"]["/api/missions"] == 3
        assert result["api_error_rates"]["/api/targets"] == 1

    def test_latency_by_endpoint(self, collector):
        # add a second label so path= appears as a standalone comma-part
        for v in range(1, 101):
            collector.observe_histogram(
                "http.request.duration_ms",
                float(v),
                {"method": "GET", "path": "/api/scan"},
            )
        result = collector.get_saas_metrics()
        assert "/api/scan" in result["latency_by_endpoint"]
        stats = result["latency_by_endpoint"]["/api/scan"]
        assert stats["count"] == 100
        assert "p50" in stats
        assert "p90" in stats
        assert "p99" in stats
