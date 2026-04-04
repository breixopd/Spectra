"""
Structured logging configuration with correlation ID support.

Provides JSON and human-readable log formatters, plus correlation ID
propagation via ContextVar for request tracing.
"""

import json
import logging
import os
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

UTC = UTC
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
    """Extracts or generates a correlation ID for each request.

    Sets both X-Correlation-ID and X-Request-ID on responses so that
    callers can trace requests regardless of which header they inspect.
    """

    HEADER = "X-Correlation-ID"
    REQUEST_ID_HEADER = "X-Request-ID"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        cid = request.headers.get(self.HEADER) or request.headers.get(self.REQUEST_ID_HEADER) or str(uuid4())
        token = correlation_id_var.set(cid)
        try:
            response = await call_next(request)
            response.headers[self.HEADER] = cid
            response.headers[self.REQUEST_ID_HEADER] = cid
            return response
        finally:
            correlation_id_var.reset(token)


class _CorrelationFilter(logging.Filter):
    """Injects correlation_id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get() or ""  # type: ignore[attr-defined]
        return True


class SensitiveFieldFilter(logging.Filter):
    """Redacts sensitive values from log records before output."""

    PATTERNS = [
        (re.compile(r'(password|passwd|pwd)"?\s*[=:]\s*"?\S+', re.IGNORECASE), r"\1=***REDACTED***"),
        (
            re.compile(r'(token|api_key|apikey|secret|authorization)"?\s*[=:]\s*"?\S+', re.IGNORECASE),
            r"\1=***REDACTED***",
        ),
        (re.compile(r"(Bearer\s+)\S+", re.IGNORECASE), r"\1***REDACTED***"),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            for pattern, replacement in self.PATTERNS:
                record.msg = pattern.sub(replacement, record.msg)
        return True


class JSONFormatter(logging.Formatter):
    """Outputs log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
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


def configure_logging(log_format: str = "", log_level: str = "") -> None:
    """Set up root logger with the appropriate formatter.

    Parameters
    ----------
    log_format:
        ``json`` for structured JSON lines, ``text`` for human-readable.
        Falls back to ``LOG_FORMAT`` env var, then ``text``.
    log_level:
        Python log-level name (e.g. ``INFO``).  Falls back to
        ``LOG_LEVEL`` env var, then ``INFO``.
    """
    fmt = (log_format or os.environ.get("LOG_FORMAT", "text")).lower()
    level_name = (log_level or os.environ.get("LOG_LEVEL", "INFO")).upper()

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_CorrelationFilter())
    handler.addFilter(SensitiveFieldFilter())

    if fmt == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(HumanFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level_name, logging.INFO))
