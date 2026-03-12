import logging
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.status import HTTP_403_FORBIDDEN

from app.core.config import settings

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
