"""
OpenTelemetry-compatible tracing and metrics for Spectra.

Follows OTel semantic conventions for metric and attribute naming
without requiring the opentelemetry-sdk.  All data is stored in-memory
and can be exported via ``/metrics`` (Prometheus text format) or the
existing ``/api/v1/observability/export/otlp`` (OTLP JSON).

Provides distributed tracing and metrics collection for:
- HTTP requests
- LLM calls
- Tool executions
- Mission workflows
- System resources (CPU, memory, GC, file descriptors)
"""

import gc
import logging
import os
import resource as _resource
from collections import deque
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from app.core.telemetry_export import (
    METRIC_DESCRIPTIONS,
    MetricData,
    MetricFamily,
    Sample,
    SpanData,
    export_otlp_format,
    get_all_metrics,
    get_resource_attributes,
)

logger = logging.getLogger("spectra.telemetry")

P = ParamSpec("P")
T = TypeVar("T")

# Backward-compatible re-exports
_METRIC_DESCRIPTIONS = METRIC_DESCRIPTIONS


class TelemetryCollector:
    """
    Collects traces and metrics for the application.

    In-memory storage for simplicity. In production, would export to
    Jaeger/Prometheus/OTLP collector.

    Features time-based expiration to prevent memory buildup.
    """

    def __init__(
        self,
        max_traces: int = 1000,
        max_metrics: int = 10000,
        trace_ttl_seconds: int = 3600,  # 1 hour default
        metric_ttl_seconds: int = 7200,  # 2 hours default
    ):
        self._traces: deque[SpanData] = deque(maxlen=max_traces)
        self._metrics: deque[MetricData] = deque(maxlen=max_metrics)
        self._max_traces = max_traces
        self._max_metrics = max_metrics
        self._trace_ttl_seconds = trace_ttl_seconds
        self._metric_ttl_seconds = metric_ttl_seconds

        # Aggregated metrics
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}

        # Service health tracking
        self._service_status: dict[str, dict[str, Any]] = {}

        # Request tracking
        self._request_count = 0
        self._error_count = 0
        self._total_latency = 0.0
        self._last_cleanup = datetime.now()

    def _cleanup_expired(self) -> None:
        """Remove expired traces and metrics based on TTL."""
        now = datetime.now()

        # Run cleanup every 10 seconds
        if (now - self._last_cleanup).total_seconds() < 10:
            return

        self._last_cleanup = now

        # Cleanup expired traces
        trace_cutoff = now.timestamp() - self._trace_ttl_seconds
        valid_traces = [
            t for t in self._traces if t.start_time.timestamp() > trace_cutoff
        ]
        self._traces = deque(valid_traces, maxlen=self._max_traces)

        # Cleanup expired metrics
        metric_cutoff = now.timestamp() - self._metric_ttl_seconds
        valid_metrics = [
            m for m in self._metrics if m.timestamp.timestamp() > metric_cutoff
        ]
        self._metrics = deque(valid_metrics, maxlen=self._max_metrics)

    def _generate_id(self) -> str:
        """Generate a random trace/span ID."""
        import secrets

        return secrets.token_hex(8)

    def create_trace(self) -> str:
        """Create a new trace and return its ID."""
        return self._generate_id()

    def start_span(
        self,
        name: str,
        trace_id: str | None = None,
        parent_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> SpanData:
        """Start a new span."""
        span = SpanData(
            trace_id=trace_id or self._generate_id(),
            span_id=self._generate_id(),
            name=name,
            parent_id=parent_id,
            attributes=attributes or {},
        )
        return span

    def end_span(
        self, span: SpanData, status: str = "ok", error: str | None = None
    ) -> None:
        """End a span and record it."""
        span.end_time = datetime.now()
        span.duration_ms = (span.end_time - span.start_time).total_seconds() * 1000
        span.status = status

        if error:
            span.attributes["error.message"] = error

        # Cleanup expired entries periodically
        self._cleanup_expired()

        # Store span
        self._traces.append(span)
        while len(self._traces) > self._max_traces:
            self._traces.popleft()

        # Update metrics
        self._request_count += 1
        self._total_latency += span.duration_ms
        if status == "error":
            self._error_count += 1

    def record_metric(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
        metric_type: str = "gauge",
    ) -> None:
        """Record a metric data point."""
        # Cleanup expired entries periodically
        self._cleanup_expired()

        metric = MetricData(
            name=name,
            value=value,
            labels=labels or {},
            metric_type=metric_type,
        )

        self._metrics.append(metric)
        while len(self._metrics) > self._max_metrics:
            self._metrics.popleft()

        # Update aggregates
        key = (
            f"{name}:{','.join(f'{k}={v}' for k, v in sorted((labels or {}).items()))}"
        )

        if metric_type == "counter":
            self._counters[key] = self._counters.get(key, 0) + value
        elif metric_type == "gauge":
            self._gauges[key] = value
        elif metric_type == "histogram":
            if key not in self._histograms:
                self._histograms[key] = []
            self._histograms[key].append(value)
            # Keep only last 1000 values
            if len(self._histograms[key]) > 1000:
                self._histograms[key] = self._histograms[key][-1000:]

    def increment_counter(
        self, name: str, value: float = 1, labels: dict[str, str] | None = None
    ) -> None:
        """Increment a counter metric."""
        self.record_metric(name, value, labels, "counter")

    def set_gauge(
        self, name: str, value: float, labels: dict[str, str] | None = None
    ) -> None:
        """Set a gauge metric."""
        self.record_metric(name, value, labels, "gauge")

    def adjust_gauge(
        self, name: str, delta: float, labels: dict[str, str] | None = None
    ) -> None:
        """Increment or decrement a gauge by *delta*."""
        key = (
            f"{name}:{','.join(f'{k}={v}' for k, v in sorted((labels or {}).items()))}"
        )
        self._gauges[key] = self._gauges.get(key, 0) + delta

    def observe_histogram(
        self, name: str, value: float, labels: dict[str, str] | None = None
    ) -> None:
        """Record a histogram observation."""
        self.record_metric(name, value, labels, "histogram")

    def update_service_status(
        self,
        service: str,
        healthy: bool,
        latency_ms: float | None = None,
        error: str | None = None,
    ) -> None:
        """Update service health status."""
        self._service_status[service] = {
            "healthy": healthy,
            "last_check": datetime.now().isoformat(),
            "latency_ms": latency_ms,
            "error": error,
        }

    @asynccontextmanager
    async def trace_span(
        self,
        name: str,
        trace_id: str | None = None,
        parent_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ):
        """Context manager for tracing a span."""
        span = self.start_span(name, trace_id, parent_id, attributes)
        try:
            yield span
            self.end_span(span, "ok")
        except Exception as e:
            self.end_span(span, "error", str(e))
            raise

    def traced(
        self,
        name: str | None = None,
        attributes: dict[str, Any] | None = None,
    ):
        """Decorator for tracing function execution."""

        def decorator(func: Callable[P, T]) -> Callable[P, T]:
            span_name = name or f"{func.__module__}.{func.__name__}"

            @wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                span = self.start_span(span_name, attributes=attributes)
                try:
                    result = await func(*args, **kwargs)
                    self.end_span(span, "ok")
                    return result
                except Exception as e:
                    self.end_span(span, "error", str(e))
                    raise

            @wraps(func)
            def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                span = self.start_span(span_name, attributes=attributes)
                try:
                    result = func(*args, **kwargs)
                    self.end_span(span, "ok")
                    return result
                except Exception as e:
                    self.end_span(span, "error", str(e))
                    raise

            import asyncio

            if asyncio.iscoroutinefunction(func):
                return async_wrapper
            return sync_wrapper

        return decorator

    # --- Statistics ---

    def get_traces(
        self,
        limit: int = 100,
        service: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get recent traces."""
        traces = list(self._traces)

        if service:
            traces = [t for t in traces if t.service == service]
        if status:
            traces = [t for t in traces if t.status == status]

        return [t.to_dict() for t in traces[-limit:]]

    def get_metrics_summary(self) -> dict[str, Any]:
        """Get aggregated metrics summary."""
        # Calculate histogram percentiles
        histogram_stats = {}
        for key, values in self._histograms.items():
            if values:
                sorted_vals = sorted(values)
                n = len(sorted_vals)
                histogram_stats[key] = {
                    "count": n,
                    "min": sorted_vals[0],
                    "max": sorted_vals[-1],
                    "avg": sum(sorted_vals) / n,
                    "p50": sorted_vals[int(n * 0.5)],
                    "p90": sorted_vals[int(n * 0.9)],
                    "p99": sorted_vals[int(n * 0.99)] if n >= 100 else sorted_vals[-1],
                }

        return {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "histograms": histogram_stats,
        }

    def get_service_health(self) -> dict[str, dict[str, Any]]:
        """Get all service health statuses."""
        return dict(self._service_status)

    def get_overview_stats(self) -> dict[str, Any]:
        """Get high-level statistics."""
        avg_latency = (
            self._total_latency / self._request_count if self._request_count > 0 else 0
        )
        error_rate = (
            self._error_count / self._request_count * 100
            if self._request_count > 0
            else 0
        )

        # Get latency distribution from traces
        # Convert deque to list for slicing
        traces_list = list(self._traces)
        latencies = [t.duration_ms for t in traces_list[-1000:] if t.duration_ms > 0]
        latency_stats = {}
        if latencies:
            sorted_latencies = sorted(latencies)
            n = len(sorted_latencies)
            latency_stats = {
                "p50_ms": round(sorted_latencies[int(n * 0.5)], 2),
                "p90_ms": round(sorted_latencies[int(n * 0.9)], 2),
                "p99_ms": round(
                    sorted_latencies[int(n * 0.99)]
                    if n >= 100
                    else sorted_latencies[-1],
                    2,
                ),
            }

        return {
            "total_requests": self._request_count,
            "total_errors": self._error_count,
            "error_rate_percent": round(error_rate, 2),
            "avg_latency_ms": round(avg_latency, 2),
            "latency_percentiles": latency_stats,
            "active_services": len(self._service_status),
            "healthy_services": sum(
                1 for s in self._service_status.values() if s.get("healthy")
            ),
            "total_traces": len(self._traces),
            "total_metrics": len(self._metrics),
        }

    def get_trace_by_id(self, trace_id: str) -> list[dict[str, Any]]:
        """Get all spans for a trace."""
        spans = [t for t in self._traces if t.trace_id == trace_id]
        return [s.to_dict() for s in spans]

    def get_slow_operations(
        self, threshold_ms: float = 1000, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Get slowest operations above threshold."""
        slow = [t for t in self._traces if t.duration_ms >= threshold_ms]
        slow.sort(key=lambda x: x.duration_ms, reverse=True)
        return [s.to_dict() for s in slow[:limit]]

    def get_error_traces(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get traces with errors."""
        errors = [t for t in self._traces if t.status == "error"]
        return [e.to_dict() for e in errors[-limit:]]

    # --- Resource attributes (OTel) ---

    def get_resource_attributes(self) -> dict[str, str]:
        """Return OTel resource attributes for this service."""
        return get_resource_attributes()

    # --- System resource collection ---

    def collect_system_resources(self) -> None:
        """Collect system resource metrics using only the stdlib."""
        usage = _resource.getrusage(_resource.RUSAGE_SELF)

        # CPU time (seconds)
        self.set_gauge(
            "process.runtime.cpython.cpu_time", usage.ru_utime, {"type": "user"}
        )
        self.set_gauge(
            "process.runtime.cpython.cpu_time", usage.ru_stime, {"type": "system"}
        )

        # Memory from /proc/self/status (Linux) — VmRSS / VmSize
        try:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        rss_kb = int(line.split()[1])
                        self.set_gauge(
                            "process.runtime.cpython.memory",
                            float(rss_kb * 1024),
                            {"type": "rss"},
                        )
                    elif line.startswith("VmSize:"):
                        vms_kb = int(line.split()[1])
                        self.set_gauge(
                            "process.runtime.cpython.memory",
                            float(vms_kb * 1024),
                            {"type": "vms"},
                        )
        except OSError:
            # Fallback: max RSS from resource module (KB on Linux)
            self.set_gauge(
                "process.runtime.cpython.memory",
                float(usage.ru_maxrss * 1024),
                {"type": "rss"},
            )

        # Open file descriptors
        try:
            fd_count = len(os.listdir(f"/proc/{os.getpid()}/fd"))
            self.set_gauge("process.open_file_descriptors", float(fd_count))
        except OSError:
            pass

        # Python GC stats
        for gen_idx, gen_stats in enumerate(gc.get_stats()):
            self.set_gauge(
                "process.runtime.cpython.gc_count",
                float(gen_stats["collections"]),
                {"generation": str(gen_idx)},
            )

    # --- Prometheus / OTel export helpers ---

    def get_all_metrics(self) -> list[MetricFamily]:
        """Return all metrics structured as MetricFamily objects."""
        return get_all_metrics(self._counters, self._gauges, self._histograms)

    def export_otlp_format(self) -> dict[str, Any]:
        """Export metrics and traces in OTLP JSON-compatible format."""
        return export_otlp_format(
            self._counters, self._gauges, self._histograms, list(self._traces)
        )

    def get_saas_metrics(self) -> dict[str, Any]:
        """Aggregate key SaaS KPIs from existing collected data."""
        # Active users from auth counters
        active_users = sum(
            v for k, v in self._counters.items()
            if k.startswith("auth.")
        )

        # Mission throughput
        missions_started = sum(
            v for k, v in self._counters.items()
            if "mission_events_total" in k and "event=started" in k
        )
        missions_completed = sum(
            v for k, v in self._counters.items()
            if "mission_events_total" in k and "event=completed" in k
        )

        # API error rates by endpoint path
        error_rates: dict[str, float] = {}
        for key, value in self._counters.items():
            if "http.server.request.errors" in key:
                # Extract route label
                for part in key.split(","):
                    if part.startswith("route="):
                        error_rates[part.split("=", 1)[1]] = value
                        break

        # Latency percentiles by endpoint
        latency_by_endpoint: dict[str, dict[str, float]] = {}
        for key, values in self._histograms.items():
            if "http.server.request.duration" in key:
                path = ""
                for part in key.split(","):
                    if part.startswith("route="):
                        path = part.split("=", 1)[1]
                        break
                if path and values:
                    sorted_v = sorted(values)
                    n = len(sorted_v)
                    latency_by_endpoint[path] = {
                        "p50": round(sorted_v[int(n * 0.5)], 2),
                        "p90": round(sorted_v[int(n * 0.9)], 2),
                        "p99": round(sorted_v[int(n * 0.99)] if n >= 100 else sorted_v[-1], 2),
                        "count": n,
                    }

        return {
            "active_users": int(active_users),
            "missions": {
                "started": int(missions_started),
                "completed": int(missions_completed),
            },
            "api_error_rates": error_rates,
            "latency_by_endpoint": latency_by_endpoint,
        }


# Global telemetry instance
telemetry = TelemetryCollector()


# --- Convenience Functions ---


def trace(name: str, **attributes):
    """Decorator for tracing function execution."""
    return telemetry.traced(name, attributes)


async def record_llm_call(
    provider: str,
    model: str,
    duration_ms: float,
    tokens: int,
    success: bool,
) -> None:
    """Record LLM call metrics."""
    labels = {"provider": provider, "model": model}

    telemetry.increment_counter("llm_calls_total", 1, labels)
    telemetry.observe_histogram("llm_duration_ms", duration_ms, labels)
    telemetry.increment_counter("llm_tokens_total", tokens, labels)

    if not success:
        telemetry.increment_counter("llm_errors_total", 1, labels)


async def record_tool_execution(
    tool_id: str,
    duration_ms: float,
    success: bool,
) -> None:
    """Record tool execution metrics."""
    labels = {"tool": tool_id}

    telemetry.increment_counter("tool_executions_total", 1, labels)
    telemetry.observe_histogram("tool_duration_ms", duration_ms, labels)

    if not success:
        telemetry.increment_counter("tool_errors_total", 1, labels)


async def record_mission_event(
    mission_id: str,
    event: str,
    phase: str | None = None,
) -> None:
    """Record mission event."""
    labels = {"event": event}
    if phase:
        labels["phase"] = phase

    telemetry.increment_counter("mission_events_total", 1, labels)


__all__ = [
    "SpanData",
    "MetricData",
    "MetricFamily",
    "Sample",
    "TelemetryCollector",
    "telemetry",
    "trace",
    "record_llm_call",
    "record_tool_execution",
    "record_mission_event",
]
