"""
Structured logging configuration with correlation ID support.

Provides JSON and human-readable log formatters, plus correlation ID
propagation via ContextVar for request tracing.
"""

import json
import logging
import os
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# ContextVar for correlation ID — accessible from any async context
correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> str | None:
    """Return the current correlation ID, if set."""
    return correlation_id_var.get()


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Extracts or generates a correlation ID for each request."""

    HEADER = "X-Correlation-ID"

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        cid = request.headers.get(self.HEADER) or str(uuid4())
        token = correlation_id_var.set(cid)
        try:
            response = await call_next(request)
            response.headers[self.HEADER] = cid
            return response
        finally:
            correlation_id_var.reset(token)


class _CorrelationFilter(logging.Filter):
    """Injects correlation_id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get() or ""  # type: ignore[attr-defined]
        return True


class JSONFormatter(logging.Formatter):
    """Outputs log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=UTC
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", ""),
        }
        if record.exc_info and record.exc_info[1] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        # Merge any extra fields passed via `logging.info("msg", extra={...})`
        for key in ("extra",):
            val = getattr(record, key, None)
            if isinstance(val, dict):
                log_entry.update(val)
        return json.dumps(log_entry, default=str)


class HumanFormatter(logging.Formatter):
    """Human-readable formatter that includes correlation ID when present."""

    FMT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    FMT_CID = "%(asctime)s | %(levelname)-8s | %(name)s | [%(correlation_id)s] %(message)s"
    DATEFMT = "%Y-%m-%d %H:%M:%S"

    def format(self, record: logging.LogRecord) -> str:
        cid = getattr(record, "correlation_id", "")
        if cid:
            self._style._fmt = self.FMT_CID
        else:
            self._style._fmt = self.FMT
        self.datefmt = self.DATEFMT
        return super().format(record)


def configure_logging() -> None:
    """Set up root logger with the appropriate formatter.

    Controlled by env var ``LOG_FORMAT``:
      - ``json``  → structured JSON lines on stdout
      - ``text``  → human-readable (default)
    """
    log_format = os.environ.get("LOG_FORMAT", "text").lower()

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_CorrelationFilter())

    if log_format == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(HumanFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
