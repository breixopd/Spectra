"""
Rate Limiting for Spectra API.

Implements token bucket rate limiting using slowapi.
Protects sensitive endpoints from abuse.
Supports per-plan tiered rate limits.
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

# ---------------------------------------------------------------------------
# Per-plan rate limit tiers (requests per minute)
# ---------------------------------------------------------------------------
# Maps plan name (lowercased) to default API rate limit.
# Plans not listed here fall back to PLAN_RATE_LIMIT_DEFAULT.
PLAN_RATE_LIMITS: dict[str, str] = {
    "free": "10/minute",
    "pro": "60/minute",
    "enterprise": "200/minute",
}
PLAN_RATE_LIMIT_DEFAULT = "10/minute"  # unauthenticated / no plan


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


def _get_plan_rate_limit(request: Request) -> str:
    """Return a dynamic rate-limit string based on the authenticated user's plan.

    Admins/superusers → unlimited (very high ceiling).
    Plan users → tier from PLAN_RATE_LIMITS.
    Unauthenticated / no plan → PLAN_RATE_LIMIT_DEFAULT.
    """
    user = getattr(getattr(request, "state", None), "user", None)
    if user is None:
        # Try JWT decode as fallback (mirrors get_user_identifier)
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                payload = decode_token(auth_header[7:])
                # Stash decoded data for later — role/plan not in JWT, return default.
                _ = payload
            except Exception:
                pass
        return PLAN_RATE_LIMIT_DEFAULT

    # Admin / superuser → effectively unlimited
    if getattr(user, "is_superuser", False) or getattr(user, "role", "") == "admin":
        return "9999/minute"

    # Resolve plan name from the preloaded _plan_name_cache on request state
    plan_name = getattr(request.state, "plan_name", None)
    if plan_name:
        return PLAN_RATE_LIMITS.get(plan_name.lower(), PLAN_RATE_LIMIT_DEFAULT)

    return PLAN_RATE_LIMIT_DEFAULT


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

    # Compute retry-after from the limit window
    retry_after = 60  # Default fallback
    if exc.limit:
        try:
            retry_after = int(exc.limit.get_expiry())
        except Exception:
            pass

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
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(retry_after),
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


def get_plan_dynamic_limit(request: Request) -> str:
    """Public dynamic limit callable for use with ``@limiter.limit``."""
    return _get_plan_rate_limit(request)


__all__ = [
    "limiter",
    "RateLimits",
    "PLAN_RATE_LIMITS",
    "PLAN_RATE_LIMIT_DEFAULT",
    "get_client_identifier",
    "get_user_identifier",
    "get_plan_dynamic_limit",
    "rate_limit_exceeded_handler",
    "limit_login",
    "limit_mission",
    "limit_tool",
]
