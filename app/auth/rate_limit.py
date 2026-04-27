"""
Rate Limiting for Spectra API.

Implements token bucket rate limiting using slowapi.
Protects sensitive endpoints from abuse.
"""

import logging
import os
import re
from collections.abc import Callable

from fastapi import Request, Response
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse

from app.infrastructure.events import EventType, events

logger = logging.getLogger(__name__)


def _decode_token_sync_no_blacklist(token: str) -> dict:
    """Sync JWT decode for rate-limiter key function (no blacklist check)."""
    import jwt as _jwt

    from app.core.config import settings

    return _jwt.decode(
        token,
        settings.JWT_SECRET_KEY.get_secret_value(),
        algorithms=[settings.JWT_ALGORITHM],
    )


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
            payload = _decode_token_sync_no_blacklist(token)
            username = payload.get("sub")
            if username:
                return f"user:{username}"
        except (OSError, RuntimeError, ValueError) as e:
            logger.debug("JWT decode failed in rate limiter: %s", e)
            return f"invalid:{get_remote_address(request)}"

    return get_client_identifier(request)


# Create limiter instance.
# Storage is configurable via RATE_LIMIT_STORAGE.
# PostgreSQL remains the persistent state store, PostgreSQL-backed app cache,
# job queue, and LISTEN/NOTIFY backbone; it does not coordinate rate-limit
# state.
# Deployment default is Redis so counters stay shared across app replicas.
# Use "memory://" mainly for tests or intentionally ephemeral local runs.
# Use Caddy's rate_limit module only if you intentionally want rate limiting
# to live entirely at the reverse proxy edge.
from app.core.config import settings as _rl_settings
from app.core.constants import API_RATE_LIMIT

# Paths exempt from rate limiting (static assets, health probes, lightweight status)
_RATE_LIMIT_EXEMPT_PREFIXES = ("/static/", "/api/health", "/api/v1/health", "/api/v1/system/status/quick")


def _rate_limit_key_func(request: Request) -> str:
    """Return rate limit key, or skip for exempt paths."""
    path = request.url.path
    if any(path.startswith(prefix) for prefix in _RATE_LIMIT_EXEMPT_PREFIXES):
        # Return a sentinel that slowapi will not track
        return "__rate_limit_exempt__"
    return get_user_identifier(request)


limiter = Limiter(
    key_func=_rate_limit_key_func,
    default_limits=[API_RATE_LIMIT],
    headers_enabled=True,  # Add rate limit headers to responses
    storage_uri=_rl_settings.RATE_LIMIT_STORAGE,
)

# Patch slowapi's _inject_headers to skip non-Response objects (WebSocket
# upgrades, SSE/EventSource, StreamingResponse subclasses that don't behave
# like a normal Response).  Without this, slowapi raises:
#   "parameter response must be an instance of starlette.responses.Response"
_original_inject_headers = Limiter._inject_headers


def _safe_inject_headers(self, response, *args, **kwargs):
    from starlette.responses import Response as _StarletteResponse

    if not isinstance(response, _StarletteResponse):
        return response
    return _original_inject_headers(self, response, *args, **kwargs)


Limiter._inject_headers = _safe_inject_headers


# --- Rate Limit Presets ---


class RateLimits:
    """Common rate limit configurations."""

    # Authentication endpoints - allows normal UI flow while preventing brute force
    # Env-var overrides let test environments raise these without weakening production.
    _RATE_FMT = re.compile(r'^\d+/(second|minute|hour|day)$')

    LOGIN = os.environ.get("RATE_LIMIT_LOGIN", "15/minute")
    SETUP = os.environ.get("RATE_LIMIT_SETUP", "10/minute")
    TOKEN_REFRESH = "30/minute"
    PROFILE_UPDATE = "5/minute"
    PASSWORD_CHANGE = "5/minute"
    ACCOUNT_DELETE = "2/hour"
    FORGOT_PASSWORD = "3/minute"
    RESET_PASSWORD = "5/minute"
    PUBLIC_REGISTER = os.environ.get("RATE_LIMIT_REGISTER", "10/minute")

    # Mission operations - moderate limits
    MISSION_START = "5/minute"
    MISSION_CONTROL = "10/minute"
    MISSION_STEER = "30/minute"

    # Tool operations - relaxed for automation
    TOOL_LIST = "60/minute"
    TOOL_EXECUTE = "20/minute"
    TOOL_UPLOAD = "5/minute"
    TOOL_INSTALL_ALL = "2/minute"
    TOOL_INSTALL = "5/minute"
    TOOL_MANAGE = "10/minute"
    TOOL_REMOVE = "5/minute"
    TOOL_TEST = "10/minute"

    # Export and read-heavy endpoints
    FINDINGS_LIST = "60/minute"
    FINDINGS_EXPORT = "60/minute"
    EXPORT_DATA = "10/minute"
    SHELL_SESSIONS = "30/minute"

    # API general - default
    API_DEFAULT = API_RATE_LIMIT
    API_HEAVY = "30/minute"

    # WebSocket - connection limits
    WS_CONNECT = "10/minute"

    # Pentest sessions — S3-backed, heavier reads
    PENTEST_SESSION_LIST = "10/minute"
    PENTEST_SESSION_READ = "30/minute"
    PENTEST_SESSION_WRITE = "20/minute"

    # VPN management
    VPN_READ = "20/minute"
    VPN_WRITE = "10/minute"

    # Target management
    TARGET_READ = "60/minute"
    TARGET_WRITE = "30/minute"

    # Observability (internal admin data)
    OBSERVABILITY = "30/minute"

    # Internal metrics endpoint (machine-to-machine, per node)
    INTERNAL_METRICS = "10/minute"

    # Billing
    BILLING = "20/minute"

    # MCP protocol endpoint
    MCP = "30/minute"

    # Session / account management
    SESSION_READ = "120/minute"
    SESSION_WRITE = "10/minute"

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        cls._validate_env_rates()

    @classmethod
    def _validate_env_rates(cls) -> None:
        for attr in ("LOGIN", "SETUP", "PUBLIC_REGISTER"):
            val = getattr(cls, attr, None)
            if val and not cls._RATE_FMT.match(val):
                raise ValueError(f"Invalid rate limit format for {attr}: {val!r}")


RateLimits._validate_env_rates()


async def rate_limit_exceeded_handler(
    request: Request,
    exc: RateLimitExceeded,
) -> Response:
    return _build_rate_limit_exceeded_response(request, exc)


def rate_limit_exceeded_handler_sync(
    request: Request,
    exc: RateLimitExceeded,
) -> Response:
    return _build_rate_limit_exceeded_response(request, exc)


def _build_rate_limit_exceeded_response(
    request: Request,
    exc: RateLimitExceeded,
) -> Response:
    """
    Custom handler for rate limit exceeded errors.

    Logs the event and returns a structured JSON response.
    """
    client_id = get_client_identifier(request)
    endpoint = request.url.path
    detail = getattr(exc, "detail", None) or str(exc)

    logger.warning(
        "Rate limit exceeded: %s on %s (limit: %s)",
        client_id,
        endpoint,
        detail,
    )

    # Emit event for monitoring
    events.emit_sync(
        EventType.RATE_LIMIT_EXCEEDED,
        source="rate_limiter",
        client_id=client_id,
        endpoint=endpoint,
        limit=str(detail),
    )

    # Compute retry-after from the limit window
    retry_after = 60  # Default fallback
    limit = getattr(exc, "limit", None)
    if limit:
        try:
            retry_after = int(limit.get_expiry())
        except (OSError, RuntimeError, ValueError, AttributeError, TypeError):
            logger.debug("Rate limit retry-after computation failed", exc_info=True)

    return JSONResponse(
        status_code=429,
        content={
            "error": "RATE_LIMIT_EXCEEDED",
            "message": f"Rate limit exceeded: {detail}",
            "retry_after_seconds": retry_after,
        },
        headers={
            "Retry-After": str(retry_after),
            "X-RateLimit-Limit": str(detail),
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


__all__ = [
    "RateLimits",
    "get_client_identifier",
    "get_user_identifier",
    "limit_login",
    "limit_mission",
    "limit_tool",
    "limiter",
    "rate_limit_exceeded_handler",
    "rate_limit_exceeded_handler_sync",
]
