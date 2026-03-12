"""
Request ID middleware for cross-service request tracing.

Delegates to CorrelationIdMiddleware which already handles:
- Generating UUID for each request if X-Request-ID / X-Correlation-ID not provided
- Storing the ID in contextvars for log injection
- Including the ID in response headers (both X-Request-ID and X-Correlation-ID)

This module re-exports the middleware and accessor for convenience.
"""

from app.core.logging_config import CorrelationIdMiddleware, get_correlation_id

RequestIDMiddleware = CorrelationIdMiddleware
get_request_id = get_correlation_id

__all__ = ["RequestIDMiddleware", "get_request_id"]
