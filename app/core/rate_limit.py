"""
Rate Limiting for Spectra API.

Implements token bucket rate limiting using slowapi.
Protects sensitive endpoints from abuse.
"""

import logging
from collections.abc import Callable

from fastapi import Request, Response
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse

from app.core.events import EventType, events
from app.core.security import decode_token

logger = logging.getLogger("spectra.core.rate_limit")


def get_client_identifier(request: Request) -> str:
    """Get client IP from the request.

    Uses request.client.host directly. X-Forwarded-For is only used
    when behind a trusted reverse proxy (Caddy/nginx), in which case
    uvicorn's --proxy-headers flag handles it automatically via
    request.client.host.
    """
    if request.client:
        return request.client.host
    return "unknown"


def get_user_identifier(request: Request) -> str:
    """
    Get user-based identifier for authenticated rate limiting.

    Falls back to IP if user not authenticated.
    """
    # Try to get user from request state (set by auth middleware)
    if hasattr(request.state, "user") and request.state.user:
        return f"user:{request.state.user.username}"

    # Try to extract from Authorization header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        try:
            payload = decode_token(token)
            username = payload.get("sub")
            if username:
                return f"user:{username}"
        except Exception as e:
            logger.debug("JWT decode failed in rate limiter: %s", e)
            return f"invalid:{get_remote_address(request)}"

    return get_client_identifier(request)


# Create limiter instance
limiter = Limiter(
    key_func=get_user_identifier,
    default_limits=["100/minute"],  # Default: 100 requests per minute
    headers_enabled=True,  # Add rate limit headers to responses
    storage_uri="memory://",
)


# --- Rate Limit Presets ---


class RateLimits:
    """Common rate limit configurations."""

    # Authentication endpoints - strict limits
    LOGIN = "5/minute"
    SETUP = "3/minute"
    TOKEN_REFRESH = "10/minute"

    # Mission operations - moderate limits
    MISSION_START = "10/minute"
    MISSION_STEER = "30/minute"

    # Tool operations - relaxed for automation
    TOOL_LIST = "60/minute"
    TOOL_EXECUTE = "20/minute"
    TOOL_UPLOAD = "5/minute"

    # API general - default
    API_DEFAULT = "100/minute"
    API_HEAVY = "30/minute"

    # WebSocket - connection limits
    WS_CONNECT = "10/minute"


async def rate_limit_exceeded_handler(
    request: Request,
    exc: RateLimitExceeded,
) -> Response:
    """
    Custom handler for rate limit exceeded errors.

    Logs the event and returns a structured JSON response.
    """
    client_id = get_client_identifier(request)
    endpoint = request.url.path

    logger.warning(
        "Rate limit exceeded: %s on %s (limit: %s)",
        client_id,
        endpoint,
        exc.detail,
    )

    # Emit event for monitoring
    events.emit_sync(
        EventType.RATE_LIMIT_EXCEEDED,
        source="rate_limiter",
        client_id=client_id,
        endpoint=endpoint,
        limit=str(exc.detail),
    )

    # Parse retry-after from headers if available
    retry_after = 60  # Default

    return JSONResponse(
        status_code=429,
        content={
            "error": "RATE_LIMIT_EXCEEDED",
            "message": f"Rate limit exceeded: {exc.detail}",
            "retry_after_seconds": retry_after,
        },
        headers={
            "Retry-After": str(retry_after),
            "X-RateLimit-Limit": str(exc.detail),
        },
    )


# --- Decorator Helpers ---


def limit_login(func: Callable) -> Callable:
    """Apply login rate limit to a function."""
    return limiter.limit(RateLimits.LOGIN)(func)


def limit_mission(func: Callable) -> Callable:
    """Apply mission rate limit to a function."""
    return limiter.limit(RateLimits.MISSION_START)(func)


def limit_tool(func: Callable) -> Callable:
    """Apply tool rate limit to a function."""
    return limiter.limit(RateLimits.TOOL_EXECUTE)(func)


__all__ = [
    "limiter",
    "RateLimits",
    "get_client_identifier",
    "get_user_identifier",
    "rate_limit_exceeded_handler",
    "limit_login",
    "limit_mission",
    "limit_tool",
]
