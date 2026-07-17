"""Tests for the observability API router endpoints."""

from unittest.mock import MagicMock, patch

import pytest

from spectra_observability.telemetry import TelemetryCollector

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_admin_user():
    user = MagicMock()
    user.is_superuser = True
    user.role = "admin"
    return user


def _make_mock_request():
    req = MagicMock()
    req.url.path = "/api/v1/observability/test"
    req.client.host = "127.0.0.1"
    req.headers = {}
    req.state = MagicMock()
    req.state.user = None
    return req


def _make_regular_user():
    user = MagicMock()
    user.is_superuser = False
    user.role = "user"
    return user


# ---------------------------------------------------------------------------
# OTLP export endpoint
# ---------------------------------------------------------------------------


class TestOtlpExportEndpoint:
    @pytest.mark.asyncio
    async def test_export_otlp_returns_valid_structure(self):
        from spectra_api.api.routers.observability import export_otlp

        collector = TelemetryCollector()
        collector.increment_counter("test.counter", 5)
        span = collector.start_span("test.span")
        collector.end_span(span)

        with patch("spectra_api.api.routers.observability.telemetry", collector):
            result = await export_otlp(request=_make_mock_request(), _current_user=_make_admin_user())

        assert "resourceMetrics" in result
        assert "resourceSpans" in result
        metrics = result["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
        assert any(m["name"] == "test.counter" for m in metrics)
        spans = result["resourceSpans"][0]["scopeSpans"][0]["spans"]
        assert len(spans) == 1

    @pytest.mark.asyncio
    async def test_export_otlp_empty_collector(self):
        from spectra_api.api.routers.observability import export_otlp

        collector = TelemetryCollector()
        with patch("spectra_api.api.routers.observability.telemetry", collector):
            result = await export_otlp(request=_make_mock_request(), _current_user=_make_admin_user())

        metrics = result["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
        spans = result["resourceSpans"][0]["scopeSpans"][0]["spans"]
        assert metrics == []
        assert spans == []


# ---------------------------------------------------------------------------
# SaaS metrics endpoint
# ---------------------------------------------------------------------------


class TestSaasMetricsEndpoint:
    @pytest.mark.asyncio
    async def test_saas_metrics_returns_kpis(self):
        from spectra_api.api.routers.observability import get_saas_metrics

        collector = TelemetryCollector()
        collector.increment_counter("auth.login", 10)
        collector.increment_counter("mission_events_total", 5, {"event": "started"})
        collector.increment_counter("mission_events_total", 3, {"event": "completed"})

        with patch("spectra_api.api.routers.observability.telemetry", collector):
            result = await get_saas_metrics(request=_make_mock_request(), _current_user=_make_admin_user())

        assert result["active_users"] == 10
        assert result["missions"]["started"] == 5
        assert result["missions"]["completed"] == 3

    @pytest.mark.asyncio
    async def test_saas_metrics_empty(self):
        from spectra_api.api.routers.observability import get_saas_metrics

        collector = TelemetryCollector()
        with patch("spectra_api.api.routers.observability.telemetry", collector):
            result = await get_saas_metrics(request=_make_mock_request(), _current_user=_make_admin_user())

        assert result["active_users"] == 0
        assert result["missions"]["started"] == 0
        assert result["missions"]["completed"] == 0


# ---------------------------------------------------------------------------
# Metrics summary endpoint
# ---------------------------------------------------------------------------


class TestMetricsSummaryEndpoint:
    @pytest.mark.asyncio
    async def test_metrics_summary(self):
        from spectra_api.api.routers.observability import get_metrics_summary

        collector = TelemetryCollector()
        collector.increment_counter("req", 1)
        collector.set_gauge("cpu", 55.0)
        collector.observe_histogram("dur", 100.0)

        with patch("spectra_api.api.routers.observability.telemetry", collector):
            result = await get_metrics_summary(request=_make_mock_request(), _current_user=_make_admin_user())

        assert "counters" in result
        assert "gauges" in result
        assert "histograms" in result


# ---------------------------------------------------------------------------
# Traces endpoints
# ---------------------------------------------------------------------------


class TestTracesEndpoints:
    @pytest.mark.asyncio
    async def test_get_traces(self):
        from spectra_api.api.routers.observability import get_traces

        collector = TelemetryCollector()
        span = collector.start_span("op1")
        collector.end_span(span)

        with patch("spectra_api.api.routers.observability.telemetry", collector):
            result = await get_traces(
                request=_make_mock_request(), limit=10, status=None, _current_user=_make_admin_user()
            )

        assert len(result) == 1
        assert result[0]["name"] == "op1"

    @pytest.mark.asyncio
    async def test_get_traces_filtered_by_status(self):
        from spectra_api.api.routers.observability import get_traces

        collector = TelemetryCollector()
        ok_span = collector.start_span("ok_op")
        collector.end_span(ok_span, "ok")
        err_span = collector.start_span("err_op")
        collector.end_span(err_span, "error", "fail")

        with patch("spectra_api.api.routers.observability.telemetry", collector):
            errors = await get_traces(
                request=_make_mock_request(), limit=10, status="error", _current_user=_make_admin_user()
            )
            oks = await get_traces(
                request=_make_mock_request(), limit=10, status="ok", _current_user=_make_admin_user()
            )

        assert len(errors) == 1
        assert errors[0]["name"] == "err_op"
        assert len(oks) == 1
        assert oks[0]["name"] == "ok_op"

    @pytest.mark.asyncio
    async def test_get_trace_by_id(self):
        from spectra_api.api.routers.observability import get_trace_by_id

        collector = TelemetryCollector()
        trace_id = collector.create_trace()
        s1 = collector.start_span("s1", trace_id=trace_id)
        collector.end_span(s1)
        s2 = collector.start_span("s2", trace_id=trace_id)
        collector.end_span(s2)
        # Unrelated trace
        other = collector.start_span("other")
        collector.end_span(other)

        with patch("spectra_api.api.routers.observability.telemetry", collector):
            result = await get_trace_by_id(
                request=_make_mock_request(), trace_id=trace_id, _current_user=_make_admin_user()
            )

        assert len(result) == 2
        assert all(r["trace_id"] == trace_id for r in result)


# ---------------------------------------------------------------------------
# Error traces and slow ops
# ---------------------------------------------------------------------------


class TestErrorAndSlowEndpoints:
    @pytest.mark.asyncio
    async def test_get_error_traces(self):
        from spectra_api.api.routers.observability import get_error_traces

        collector = TelemetryCollector()
        err = collector.start_span("fail")
        collector.end_span(err, "error", "broken")
        ok = collector.start_span("success")
        collector.end_span(ok, "ok")

        with patch("spectra_api.api.routers.observability.telemetry", collector):
            result = await get_error_traces(request=_make_mock_request(), limit=10, _current_user=_make_admin_user())

        assert len(result) == 1
        assert result[0]["name"] == "fail"

    @pytest.mark.asyncio
    async def test_get_slow_operations(self):
        from spectra_api.api.routers.observability import get_slow_operations

        collector = TelemetryCollector()
        # Create a span with artificial high duration
        span = collector.start_span("slow_op")
        span.duration_ms = 2000.0
        span.end_time = span.start_time
        collector._traces.append(span)

        with patch("spectra_api.api.routers.observability.telemetry", collector):
            result = await get_slow_operations(
                request=_make_mock_request(), threshold_ms=1000, limit=5, _current_user=_make_admin_user()
            )

        assert len(result) == 1
        assert result[0]["name"] == "slow_op"


# ---------------------------------------------------------------------------
# Circuit breaker reset (superuser check)
# ---------------------------------------------------------------------------


class TestCircuitBreakerReset:
    @pytest.mark.asyncio
    async def test_reset_circuit_breakers_as_superuser(self):
        from spectra_api.api.routers.observability import reset_circuit_breakers

        mock_cbs = MagicMock()
        with patch("spectra_api.api.routers.observability.circuit_breakers", mock_cbs):
            result = await reset_circuit_breakers(request=_make_mock_request(), _current_user=_make_admin_user())

        assert result["status"] == "ok"
        mock_cbs.reset_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset_circuit_breakers_denied_for_non_superuser(self):
        from fastapi import HTTPException

        from spectra_api.api.routers.observability import reset_circuit_breakers

        with pytest.raises(HTTPException) as exc_info:
            await reset_circuit_breakers(request=_make_mock_request(), _current_user=_make_regular_user())

        assert exc_info.value.status_code == 403
