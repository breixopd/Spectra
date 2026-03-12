import logging
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.status import HTTP_403_FORBIDDEN

from app.core.config import settings
from app.core.security import decode_token

logger = logging.getLogger("spectra.middleware")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce

        # Origin validation for state-changing requests
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            origin = request.headers.get("origin")
            if origin and not settings.DEBUG:
                allowed = False
                for allowed_origin in settings.CORS_ORIGINS:
                    if allowed_origin == "*" or origin == allowed_origin:
                        allowed = True
                        break

                if not allowed:
                    logger.warning(
                        "Blocked cross-origin request from %s to %s %s", origin, request.method, request.url.path
                    )
                    return Response("Invalid Origin", status_code=HTTP_403_FORBIDDEN)
            elif origin and settings.DEBUG:
                allowed_origins = settings.CORS_ORIGINS
                if origin not in allowed_origins:
                    logger.debug("Cross-origin request from %s allowed (DEBUG mode)", origin)

        response = await call_next(request)

        # Headers for security
        headers = {
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "X-XSS-Protection": "0",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
        }
        # HSTS only in production (non-DEBUG) to avoid issues with local HTTP
        if not settings.DEBUG:
            headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        for key, value in headers.items():
            response.headers[key] = value

        # CSP - all assets served locally for self-contained deployment
        if not request.url.path.startswith("/api/"):
            # Restrict WebSocket connect-src to the app's own host
            host = request.headers.get("host", "localhost")
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                f"script-src 'self' 'nonce-{nonce}'; "
                "style-src 'self' 'unsafe-inline'; "
                "font-src 'self'; "
                "img-src 'self' data:; "
                f"connect-src 'self' ws://{host} wss://{host}; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "form-action 'self';"
            )

        return response


class PlanRateLimitMiddleware(BaseHTTPMiddleware):
    """Resolve the authenticated user's plan name and stash it on ``request.state``.

    This runs *before* SlowAPIMiddleware so the dynamic rate-limit callable
    in ``rate_limit.py`` can read ``request.state.plan_name``.
    """

    # In-memory cache: user_id → plan_name (cleared each 5 min via TTL)
    _cache: dict[str, tuple[str, float]] = {}
    _CACHE_TTL = 300  # seconds

    async def dispatch(self, request: Request, call_next) -> Response:
        import time

        # Try to identify user from token (lightweight, no DB hit for cached)
        auth_header = request.headers.get("authorization", "")
        username: str | None = None
        if auth_header.startswith("Bearer "):
            try:
                payload = decode_token(auth_header[7:])
                username = payload.get("sub")
            except Exception:
                pass

        # If we have a username, look up plan from cache or DB
        if username:
            now = time.time()
            cached = self._cache.get(username)
            if cached and now - cached[1] < self._CACHE_TTL:
                request.state.plan_name = cached[0]
            else:
                plan_name = await self._resolve_plan_name(username)
                if plan_name:
                    self._cache[username] = (plan_name, now)
                    request.state.plan_name = plan_name

        return await call_next(request)

    @staticmethod
    async def _resolve_plan_name(username: str) -> str | None:
        """Fetch the plan name for a username from the DB (async)."""
        try:
            from sqlalchemy import select

            from app.core.database import async_session_maker
            from app.models.plan import Plan
            from app.models.user import User

            async with async_session_maker() as session:
                result = await session.execute(select(User).where(User.username == username))
                user = result.scalar_one_or_none()
                if not user or not user.plan_id:
                    return None
                plan_result = await session.execute(select(Plan.name).where(Plan.id == user.plan_id))
                return plan_result.scalar_one_or_none()
        except Exception as exc:
            logger.debug("Plan lookup failed for %s: %s", username, exc)
            return None
