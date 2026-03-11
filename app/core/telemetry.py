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
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps
from typing import Any, ParamSpec, TypeVar

logger = logging.getLogger("spectra.telemetry")

P = ParamSpec("P")
T = TypeVar("T")

# ---------------------------------------------------------------------------
# OTel metric description registry
# ---------------------------------------------------------------------------
_METRIC_DESCRIPTIONS: dict[str, str] = {
    "http.server.requests": "Total HTTP requests received",
    "http.server.request.duration": "HTTP request duration in milliseconds",
    "http.server.request.errors": "HTTP requests that resulted in 5xx errors",
    "http.server.active_requests": "Number of in-flight HTTP requests",
    "db.client.connections.usage": "Database connection pool usage",
    "process.runtime.cpython.memory": "Process memory usage in bytes",
    "process.runtime.cpython.cpu_time": "Cumulative CPU time in seconds",
    "process.runtime.cpython.gc_count": "Python GC collection count by generation",
    "process.open_file_descriptors": "Open file descriptor count",
    "llm_calls_total": "Total LLM API calls",
    "llm_duration_ms": "LLM call duration in milliseconds",
    "llm_tokens_total": "Total LLM tokens consumed",
    "llm_errors_total": "Failed LLM API calls",
    "tool_executions_total": "Total tool executions",
    "tool_duration_ms": "Tool execution duration in milliseconds",
    "tool_errors_total": "Failed tool executions",
    "mission_events_total": "Mission lifecycle events",
}


@dataclass
class Sample:
    """A single metric sample with labels and value."""

    labels: dict[str, str]
    value: float


@dataclass
class MetricFamily:
    """A named collection of samples (Prometheus-style metric family)."""

    name: str
    description: str
    type: str  # "counter", "gauge", "summary"
    samples: list[Sample] = field(default_factory=list)


@dataclass
class SpanData:
    """Represents a trace span."""

    trace_id: str
    span_id: str
    name: str
    service: str = "spectra"
    parent_id: str | None = None
    start_time: datetime = field(default_factory=datetime.now)
    end_time: datetime | None = None
    duration_ms: float = 0.0
    status: str = "ok"
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage/display."""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "name": self.name,
            "service": self.service,
            "parent_id": self.parent_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "attributes": self.attributes,
            "events": self.events,
        }


@dataclass
class MetricData:
    """Represents a metric data point."""

    name: str
    value: float
    timestamp: datetime = field(default_factory=datetime.now)
    labels: dict[str, str] = field(default_factory=dict)
    metric_type: str = "gauge"  # gauge, counter, histogram

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "timestamp": self.timestamp.isoformat(),
            "labels": self.labels,
            "type": self.metric_type,
        }


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
        from app.core.config import settings
        from app.version import __version__

        return {
            "service.name": settings.OTEL_SERVICE_NAME,
            "service.version": __version__,
            "deployment.environment": "development" if settings.DEBUG else "production",
            "telemetry.sdk.language": "python",
        }

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
        """Return all metrics structured as MetricFamily objects.

        Suitable for rendering into Prometheus text exposition format.
        """
        families: dict[str, MetricFamily] = {}

        def _parse_labels(label_str: str) -> dict[str, str]:
            if not label_str:
                return {}
            labels: dict[str, str] = {}
            for part in label_str.split(","):
                if "=" in part:
                    k, v = part.split("=", 1)
                    labels[k] = v
            return labels

        # Counters
        for key, value in self._counters.items():
            name, label_str = key.split(":", 1)
            labels = _parse_labels(label_str)
            if name not in families:
                desc = _METRIC_DESCRIPTIONS.get(name, "")
                families[name] = MetricFamily(
                    name=name, description=desc, type="counter"
                )
            families[name].samples.append(Sample(labels=labels, value=value))

        # Gauges
        for key, value in self._gauges.items():
            name, label_str = key.split(":", 1)
            labels = _parse_labels(label_str)
            if name not in families:
                desc = _METRIC_DESCRIPTIONS.get(name, "")
                families[name] = MetricFamily(
                    name=name, description=desc, type="gauge"
                )
            families[name].samples.append(Sample(labels=labels, value=value))

        # Histograms → emitted as "summary" (quantiles + _count + _sum)
        for key, values in self._histograms.items():
            name, label_str = key.split(":", 1)
            labels = _parse_labels(label_str)
            if not values:
                continue
            sorted_v = sorted(values)
            n = len(sorted_v)

            if name not in families:
                desc = _METRIC_DESCRIPTIONS.get(name, "")
                families[name] = MetricFamily(
                    name=name, description=desc, type="summary"
                )

            for q, q_label in ((0.5, "0.5"), (0.9, "0.9"), (0.99, "0.99")):
                idx = min(int(n * q), n - 1)
                families[name].samples.append(
                    Sample(
                        labels={**labels, "quantile": q_label},
                        value=round(sorted_v[idx], 4),
                    )
                )

            # _count / _sum as separate families
            count_name = f"{name}_count"
            sum_name = f"{name}_sum"
            if count_name not in families:
                families[count_name] = MetricFamily(
                    name=count_name, description="", type="counter"
                )
            families[count_name].samples.append(
                Sample(labels=labels, value=float(n))
            )
            if sum_name not in families:
                families[sum_name] = MetricFamily(
                    name=sum_name, description="", type="counter"
                )
            families[sum_name].samples.append(
                Sample(labels=labels, value=round(sum(sorted_v), 4))
            )

        return list(families.values())

    def export_otlp_format(self) -> dict[str, Any]:
        """Export metrics and traces in OTLP JSON-compatible format."""
        res_attrs = self.get_resource_attributes()
        resource_attrs = [
            {"key": k, "value": {"stringValue": v}} for k, v in res_attrs.items()
        ]
        resource = {"attributes": resource_attrs}
        now_ns = int(datetime.now().timestamp() * 1e9)

        # --- metrics ---
        otlp_metrics: list[dict[str, Any]] = []

        for key, value in self._counters.items():
            name = key.split(":")[0]
            otlp_metrics.append({
                "name": name,
                "sum": {
                    "dataPoints": [{
                        "asDouble": value,
                        "timeUnixNano": str(now_ns),
                        "isMonotonic": True,
                        "aggregationTemporality": 2,
                    }],
                },
            })

        for key, values in self._histograms.items():
            name = key.split(":")[0]
            if not values:
                continue
            sorted_v = sorted(values)
            otlp_metrics.append({
                "name": name,
                "histogram": {
                    "dataPoints": [{
                        "count": str(len(sorted_v)),
                        "sum": sum(sorted_v),
                        "min": sorted_v[0],
                        "max": sorted_v[-1],
                        "timeUnixNano": str(now_ns),
                        "aggregationTemporality": 2,
                    }],
                },
            })

        for key, value in self._gauges.items():
            name = key.split(":")[0]
            otlp_metrics.append({
                "name": name,
                "gauge": {
                    "dataPoints": [{
                        "asDouble": value,
                        "timeUnixNano": str(now_ns),
                    }],
                },
            })

        # --- traces ---
        otlp_spans: list[dict[str, Any]] = []
        for span in self._traces:
            otlp_span: dict[str, Any] = {
                "traceId": span.trace_id,
                "spanId": span.span_id,
                "name": span.name,
                "kind": 1,  # SPAN_KIND_INTERNAL
                "startTimeUnixNano": str(int(span.start_time.timestamp() * 1e9)),
                "status": {"code": 2 if span.status == "error" else 1},
                "attributes": [
                    {"key": k, "value": {"stringValue": str(v)}}
                    for k, v in span.attributes.items()
                ],
            }
            if span.end_time:
                otlp_span["endTimeUnixNano"] = str(int(span.end_time.timestamp() * 1e9))
            if span.parent_id:
                otlp_span["parentSpanId"] = span.parent_id
            otlp_spans.append(otlp_span)

        return {
            "resourceMetrics": [{
                "resource": resource,
                "scopeMetrics": [{
                    "scope": {"name": "spectra.telemetry"},
                    "metrics": otlp_metrics,
                }],
            }],
            "resourceSpans": [{
                "resource": resource,
                "scopeSpans": [{
                    "scope": {"name": "spectra.telemetry"},
                    "spans": otlp_spans,
                }],
            }],
        }

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
