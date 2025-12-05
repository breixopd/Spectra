from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.status import HTTP_403_FORBIDDEN

from app.core.config import settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
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
                    return Response("Invalid Origin", status_code=HTTP_403_FORBIDDEN)

        response = await call_next(request)

        # Headers for security
        headers = {
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "X-XSS-Protection": "1; mode=block",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
        }
        for key, value in headers.items():
            response.headers[key] = value

        # CSP - Relaxed for dashboard, stricter for API
        if not request.url.path.startswith("/api/"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://unpkg.com https://cdn.jsdelivr.net https://cdn.tailwindcss.com https://cdnjs.cloudflare.com; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
                "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
                "img-src 'self' data: https://*.tile.openstreetmap.org https://*.basemaps.cartocdn.com; "
                "connect-src 'self' ws: wss: https://unpkg.com; "
                "frame-ancestors 'none';"
            )

        return response
