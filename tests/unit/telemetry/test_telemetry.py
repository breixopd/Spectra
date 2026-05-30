from unittest.mock import AsyncMock, patch

import pytest

from spectra_observability.telemetry import (
    MetricData,
    SpanData,
    TelemetryCollector,
    record_llm_call,
    record_mission_event,
    record_tool_execution,
)


def test_span_data_to_dict():
    span = SpanData(trace_id="t1", span_id="s1", name="test")
    d = span.to_dict()
    assert d["trace_id"] == "t1"
    assert d["span_id"] == "s1"
    assert d["name"] == "test"
    assert d["end_time"] is None


def test_metric_data_to_dict():
    m = MetricData(name="requests", value=5.0, labels={"method": "GET"})
    d = m.to_dict()
    assert d["name"] == "requests"
    assert d["value"] == 5.0
    assert d["labels"] == {"method": "GET"}


def test_telemetry_collector_create_trace():
    tc = TelemetryCollector()
    trace_id = tc.create_trace()
    assert len(trace_id) == 16


def test_telemetry_collector_start_span():
    tc = TelemetryCollector()
    span = tc.start_span("test-span")
    assert span.name == "test-span"
    assert span.trace_id is not None
    assert span.span_id is not None


def test_telemetry_collector_end_span():
    tc = TelemetryCollector()
    span = tc.start_span("test")
    tc.end_span(span, status="ok")
    assert span.end_time is not None
    assert span.duration_ms >= 0
    assert span.status == "ok"


def test_telemetry_collector_end_span_error():
    tc = TelemetryCollector()
    span = tc.start_span("test")
    tc.end_span(span, status="error", error="boom")
    assert span.status == "error"
    assert span.attributes["error.message"] == "boom"


def test_telemetry_collector_record_metric_gauge():
    tc = TelemetryCollector()
    tc.record_metric("cpu", 0.5, labels={"host": "h1"}, metric_type="gauge")
    assert len(tc._metrics) == 1
    assert tc._gauges["cpu:host=h1"] == 0.5


def test_telemetry_collector_record_metric_counter():
    tc = TelemetryCollector()
    tc.record_metric("requests", 1, metric_type="counter")
    tc.record_metric("requests", 2, metric_type="counter")
    assert tc._counters["requests:"] == 3


def test_telemetry_collector_record_metric_histogram():
    tc = TelemetryCollector()
    tc.record_metric("latency", 100, metric_type="histogram")
    tc.record_metric("latency", 200, metric_type="histogram")
    assert len(tc._histograms["latency:"]) == 2


def test_telemetry_collector_increment_counter():
    tc = TelemetryCollector()
    tc.increment_counter("errors")
    tc.increment_counter("errors", 2)
    assert tc._counters["errors:"] == 3


def test_telemetry_collector_set_gauge():
    tc = TelemetryCollector()
    tc.set_gauge("memory", 80)
    assert tc._gauges["memory:"] == 80


def test_telemetry_collector_observe_histogram():
    tc = TelemetryCollector()
    tc.observe_histogram("duration", 50)
    assert len(tc._histograms["duration:"]) == 1


def test_telemetry_collector_update_service_status():
    tc = TelemetryCollector()
    tc.update_service_status("db", True, latency_ms=5.0)
    assert tc._service_status["db"]["healthy"] is True
    assert tc._service_status["db"]["latency_ms"] == 5.0


@pytest.mark.asyncio
async def test_telemetry_collector_trace_span():
    tc = TelemetryCollector()
    async with tc.trace_span("async-op") as span:
        assert span.name == "async-op"
    assert span.end_time is not None
    assert span.status == "ok"


@pytest.mark.asyncio
async def test_telemetry_collector_trace_span_error():
    tc = TelemetryCollector()
    with pytest.raises(RuntimeError):
        async with tc.trace_span("async-op") as span:
            raise RuntimeError("fail")
    assert span.status == "error"


def test_telemetry_collector_traced_sync():
    tc = TelemetryCollector()

    @tc.traced(name="sync_func")
    def sync_func():
        return 42

    result = sync_func()
    assert result == 42
    assert len(tc._traces) == 1
    assert tc._traces[0].name == "sync_func"


@pytest.mark.asyncio
async def test_telemetry_collector_traced_async():
    tc = TelemetryCollector()

    @tc.traced(name="async_func")
    async def async_func():
        return 42

    result = await async_func()
    assert result == 42
    assert len(tc._traces) == 1
    assert tc._traces[0].name == "async_func"


def test_telemetry_collector_traced_error_sync():
    tc = TelemetryCollector()

    @tc.traced(name="sync_err")
    def sync_err():
        raise RuntimeError("fail")

    with pytest.raises(RuntimeError):
        sync_err()
    assert tc._traces[0].status == "error"


@pytest.mark.asyncio
async def test_telemetry_collector_traced_error_async():
    tc = TelemetryCollector()

    @tc.traced(name="async_err")
    async def async_err():
        raise RuntimeError("fail")

    with pytest.raises(RuntimeError):
        await async_err()
    assert tc._traces[0].status == "error"


def test_telemetry_collector_export_otlp_format():
    tc = TelemetryCollector()
    tc.increment_counter("requests", 5, {"path": "/api"})
    tc.set_gauge("cpu", 0.5)
    tc.observe_histogram("latency", 100)
    span = tc.start_span("test")
    tc.end_span(span)

    data = tc.export_otlp_format()
    assert "resourceMetrics" in data
    assert "resourceSpans" in data
    assert len(data["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]) > 0
    assert len(data["resourceSpans"][0]["scopeSpans"][0]["spans"]) == 1


@pytest.mark.asyncio
async def test_telemetry_collector_push_to_collector_no_endpoint():
    tc = TelemetryCollector()
    with patch("spectra_common.config.get_settings") as mock_settings:
        mock_settings.return_value.OTEL_EXPORTER_ENDPOINT = ""
        result = await tc.push_to_collector()
    assert result is False


@pytest.mark.asyncio
async def test_telemetry_collector_push_to_collector_success():
    tc = TelemetryCollector()
    tc.increment_counter("requests", 1)
    span = tc.start_span("test")
    tc.end_span(span)
    with patch("spectra_common.config.get_settings") as mock_settings:
        mock_settings.return_value.OTEL_EXPORTER_ENDPOINT = "http://otel:4318"
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tc.push_to_collector()
    assert result is True


def test_telemetry_collector_get_saas_metrics():
    tc = TelemetryCollector()
    tc.increment_counter("auth.login", 3)
    tc.increment_counter("mission_events_total", 2, {"event": "started"})
    tc.increment_counter("mission_events_total", 1, {"event": "completed"})
    tc.increment_counter("http.requests.errors", 1, {"path": "/api", "method": "GET"})
    tc.observe_histogram("http.request.duration_ms", 50, {"path": "/api", "method": "GET"})
    tc.observe_histogram("http.request.duration_ms", 150, {"path": "/api", "method": "GET"})

    metrics = tc.get_saas_metrics()
    assert metrics["active_users"] == 3
    assert metrics["missions"]["started"] == 2
    assert metrics["missions"]["completed"] == 1
    assert "/api" in metrics["api_error_rates"]
    assert "/api" in metrics["latency_by_endpoint"]


@pytest.mark.asyncio
async def test_record_llm_call():
    await record_llm_call("openai", "gpt-4", 500, 100, True)
    assert True


@pytest.mark.asyncio
async def test_record_llm_call_failure():
    await record_llm_call("openai", "gpt-4", 500, 100, False)
    assert True


@pytest.mark.asyncio
async def test_record_tool_execution():
    await record_tool_execution("nmap", 2000, True)
    assert True


@pytest.mark.asyncio
async def test_record_mission_event():
    await record_mission_event("m1", "started", "discovery")
    assert True


def test_trace_decorator():
    from spectra_observability.telemetry import trace

    @trace(name="traced_func")
    def traced_func():
        return 42

    result = traced_func()
    assert result == 42


def test_telemetry_collector_histogram_limit():
    tc = TelemetryCollector()
    for i in range(1005):
        tc.observe_histogram("h", float(i))
    assert len(tc._histograms["h:"]) == 1000


@pytest.mark.asyncio
async def test_telemetry_collector_start_export_loop_no_endpoint():
    tc = TelemetryCollector()
    with patch("spectra_common.config.get_settings") as mock_settings:
        mock_settings.return_value.OTEL_EXPORTER_ENDPOINT = ""
        result = await tc.start_export_loop()
    assert result is None


def test_telemetry_collector_get_traces():
    tc = TelemetryCollector()
    span1 = tc.start_span("svc1")
    span1.service = "svc1"
    tc.end_span(span1)
    span2 = tc.start_span("svc2")
    span2.service = "svc2"
    tc.end_span(span2, status="error")

    traces = tc.get_traces(service="svc1")
    assert len(traces) == 1
    assert traces[0]["name"] == "svc1"

    traces = tc.get_traces(status="error")
    assert len(traces) == 1
    assert traces[0]["status"] == "error"


def test_telemetry_collector_get_metrics_summary():
    tc = TelemetryCollector()
    tc.increment_counter("requests", 5)
    tc.set_gauge("cpu", 0.8)
    tc.observe_histogram("latency", 100)

    summary = tc.get_metrics_summary()
    assert "counters" in summary
    assert "gauges" in summary
    assert "histograms" in summary
    assert summary["counters"]["requests:"] == 5


@pytest.mark.asyncio
async def test_telemetry_collector_push_to_collector_error():
    tc = TelemetryCollector()
    tc.increment_counter("x", 1)
    with patch("spectra_common.config.get_settings") as mock_settings:
        mock_settings.return_value.OTEL_EXPORTER_ENDPOINT = "http://otel:4318"
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=OSError("connection failed"))
            mock_client_cls.return_value = mock_client
            result = await tc.push_to_collector()
    assert result is False
