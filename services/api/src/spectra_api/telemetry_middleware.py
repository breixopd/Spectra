"""HTTP request telemetry middleware.

Records request count, duration, active-request gauge, and error
counters via the global TelemetryCollector instance.
"""

import re
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from spectra_api.bootstrap.logging_config import get_correlation_id
from spectra_platform.telemetry.telemetry import telemetry

# Pre-compiled pattern: one or more path segments that look like IDs
# (UUIDs, integers, hex strings ≥6 chars)
_ID_SEGMENT = re.compile(
    r"/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"|\d+"
    r"|[0-9a-fA-F]{6,})"
)


def _normalize_path(path: str) -> str:
    """Replace dynamic ID segments with ``{id}`` to limit label cardinality."""
    return _ID_SEGMENT.sub("/{id}", path)


class TelemetryMiddleware(BaseHTTPMiddleware):
    """Collects per-request metrics via :pydata:`telemetry`."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # Skip static assets — they are high-volume, low-value.
        if path.startswith("/static/"):
            return await call_next(request)

        method = request.method
        path_template = _normalize_path(path)
        correlation_id = get_correlation_id() or ""

        # Track active requests
        telemetry.increment_counter("http.requests.active")

        start = time.monotonic()
        try:
            response = await call_next(request)
        except (OSError, RuntimeError, ValueError):
            elapsed_ms = (time.monotonic() - start) * 1000
            telemetry.increment_counter("http.requests.active", -1)

            labels = {
                "method": method,
                "path_template": path_template,
                "status_code": "500",
            }
            if correlation_id:
                labels["correlation_id"] = correlation_id

            telemetry.increment_counter("http.requests.total", 1, labels)
            telemetry.observe_histogram("http.request.duration_ms", elapsed_ms, labels)
            telemetry.increment_counter("http.requests.errors", 1, labels)
            raise

        elapsed_ms = (time.monotonic() - start) * 1000
        telemetry.increment_counter("http.requests.active", -1)

        status_code = str(response.status_code)
        labels = {
            "method": method,
            "path_template": path_template,
            "status_code": status_code,
        }
        if correlation_id:
            labels["correlation_id"] = correlation_id

        telemetry.increment_counter("http.requests.total", 1, labels)
        telemetry.observe_histogram("http.request.duration_ms", elapsed_ms, labels)

        if response.status_code >= 500:
            telemetry.increment_counter("http.requests.errors", 1, labels)

        return response
