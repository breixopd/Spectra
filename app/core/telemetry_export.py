"""Telemetry data models and export helpers (Prometheus / OTLP)."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


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


# OTel metric description registry
METRIC_DESCRIPTIONS: dict[str, str] = {
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


def get_resource_attributes() -> dict[str, str]:
    """Return OTel resource attributes for this service."""
    from app.core.config import settings
    from app.version import __version__

    return {
        "service.name": settings.OTEL_SERVICE_NAME,
        "service.version": __version__,
        "deployment.environment": "development" if settings.DEBUG else "production",
        "telemetry.sdk.language": "python",
    }


def get_all_metrics(
    counters: dict[str, float],
    gauges: dict[str, float],
    histograms: dict[str, list[float]],
) -> list[MetricFamily]:
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
    for key, value in counters.items():
        name, label_str = key.split(":", 1)
        labels = _parse_labels(label_str)
        if name not in families:
            desc = METRIC_DESCRIPTIONS.get(name, "")
            families[name] = MetricFamily(name=name, description=desc, type="counter")
        families[name].samples.append(Sample(labels=labels, value=value))

    # Gauges
    for key, value in gauges.items():
        name, label_str = key.split(":", 1)
        labels = _parse_labels(label_str)
        if name not in families:
            desc = METRIC_DESCRIPTIONS.get(name, "")
            families[name] = MetricFamily(name=name, description=desc, type="gauge")
        families[name].samples.append(Sample(labels=labels, value=value))

    # Histograms → emitted as "summary" (quantiles + _count + _sum)
    for key, values in histograms.items():
        name, label_str = key.split(":", 1)
        labels = _parse_labels(label_str)
        if not values:
            continue
        sorted_v = sorted(values)
        n = len(sorted_v)

        if name not in families:
            desc = METRIC_DESCRIPTIONS.get(name, "")
            families[name] = MetricFamily(name=name, description=desc, type="summary")

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
            families[count_name] = MetricFamily(name=count_name, description="", type="counter")
        families[count_name].samples.append(Sample(labels=labels, value=float(n)))
        if sum_name not in families:
            families[sum_name] = MetricFamily(name=sum_name, description="", type="counter")
        families[sum_name].samples.append(Sample(labels=labels, value=round(sum(sorted_v), 4)))

    return list(families.values())


def export_otlp_format(
    counters: dict[str, float],
    gauges: dict[str, float],
    histograms: dict[str, list[float]],
    traces: list[SpanData],
) -> dict[str, Any]:
    """Export metrics and traces in OTLP JSON-compatible format."""
    res_attrs = get_resource_attributes()
    resource_attrs = [{"key": k, "value": {"stringValue": v}} for k, v in res_attrs.items()]
    resource = {"attributes": resource_attrs}
    now_ns = int(datetime.now().timestamp() * 1e9)

    # --- metrics ---
    otlp_metrics: list[dict[str, Any]] = []

    for key, value in counters.items():
        name = key.split(":")[0]
        otlp_metrics.append(
            {
                "name": name,
                "sum": {
                    "dataPoints": [
                        {
                            "asDouble": value,
                            "timeUnixNano": str(now_ns),
                            "isMonotonic": True,
                            "aggregationTemporality": 2,
                        }
                    ],
                },
            }
        )

    for key, values in histograms.items():
        name = key.split(":")[0]
        if not values:
            continue
        sorted_v = sorted(values)
        otlp_metrics.append(
            {
                "name": name,
                "histogram": {
                    "dataPoints": [
                        {
                            "count": str(len(sorted_v)),
                            "sum": sum(sorted_v),
                            "min": sorted_v[0],
                            "max": sorted_v[-1],
                            "timeUnixNano": str(now_ns),
                            "aggregationTemporality": 2,
                        }
                    ],
                },
            }
        )

    for key, value in gauges.items():
        name = key.split(":")[0]
        otlp_metrics.append(
            {
                "name": name,
                "gauge": {
                    "dataPoints": [
                        {
                            "asDouble": value,
                            "timeUnixNano": str(now_ns),
                        }
                    ],
                },
            }
        )

    # --- traces ---
    otlp_spans: list[dict[str, Any]] = []
    for span in traces:
        otlp_span: dict[str, Any] = {
            "traceId": span.trace_id,
            "spanId": span.span_id,
            "name": span.name,
            "kind": 1,  # SPAN_KIND_INTERNAL
            "startTimeUnixNano": str(int(span.start_time.timestamp() * 1e9)),
            "status": {"code": 2 if span.status == "error" else 1},
            "attributes": [{"key": k, "value": {"stringValue": str(v)}} for k, v in span.attributes.items()],
        }
        if span.end_time:
            otlp_span["endTimeUnixNano"] = str(int(span.end_time.timestamp() * 1e9))
        if span.parent_id:
            otlp_span["parentSpanId"] = span.parent_id
        otlp_spans.append(otlp_span)

    return {
        "resourceMetrics": [
            {
                "resource": resource,
                "scopeMetrics": [
                    {
                        "scope": {"name": "spectra.telemetry"},
                        "metrics": otlp_metrics,
                    }
                ],
            }
        ],
        "resourceSpans": [
            {
                "resource": resource,
                "scopeSpans": [
                    {
                        "scope": {"name": "spectra.telemetry"},
                        "spans": otlp_spans,
                    }
                ],
            }
        ],
    }
