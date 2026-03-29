import logging
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.status import HTTP_403_FORBIDDEN

from app.core.config import settings

logger = logging.getLogger(__name__)


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
                    logger.warning("Blocked cross-origin request from %s to %s %s", origin, request.method, request.url.path)
                    return Response("Invalid Origin", status_code=HTTP_403_FORBIDDEN)
            elif origin and settings.DEBUG:
                allowed_origins = settings.CORS_ORIGINS
                if origin not in allowed_origins:
                    logger.debug("Cross-origin request from %s allowed (DEBUG mode)", origin)

        # --- CSRF Protection (Double-Submit Cookie) ---
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            auth_header = request.headers.get("authorization", "")
            api_key = request.headers.get("x-api-key", "")
            access_token = request.cookies.get("access_token")
            if not auth_header and not api_key and access_token:
                csrf_cookie = request.cookies.get("csrf_token")
                csrf_header = request.headers.get("x-csrf-token")
                if not csrf_cookie or not csrf_header or not secrets.compare_digest(csrf_cookie, csrf_header):
                    logger.warning("CSRF validation failed for %s %s", request.method, request.url.path)
                    return Response("CSRF validation failed", status_code=HTTP_403_FORBIDDEN)

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

        # CSP - all assets served locally (no external CDN dependencies)
        if not request.url.path.startswith("/api/"):
            # Restrict WebSocket connect-src to the app's own host
            host = request.headers.get("host", "localhost")
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                f"script-src 'self' 'nonce-{nonce}'; "
                "style-src 'self' 'unsafe-inline'; "
                "font-src 'self'; "
                "img-src 'self' data: https://*.basemaps.cartocdn.com; "
                f"connect-src 'self' ws://{host} wss://{host}; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "form-action 'self';"
            )

        # Set CSRF cookie for browser clients (non-API requests)
        if not request.url.path.startswith("/api/") and "csrf_token" not in request.cookies:
            csrf_tok = secrets.token_urlsafe(32)
            response.set_cookie(
                "csrf_token",
                csrf_tok,
                httponly=False,
                secure=not settings.DEBUG,
                samesite="strict",
                max_age=86400,
            )

        return response
