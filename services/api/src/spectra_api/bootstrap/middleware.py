import ipaddress as _ipaddress
import logging
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.status import HTTP_403_FORBIDDEN
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from spectra_common.config import settings

logger = logging.getLogger(__name__)


class _RequestBodyTooLarge(BaseException):
    """Internal control-flow sentinel that bypasses Starlette's 500 handler."""


class RequestBodySizeLimitMiddleware:
    """Enforce request limits against both declared and streamed body bytes.

    ``Content-Length`` is only an early rejection optimization: clients can
    omit or lie about it.  The ASGI receive wrapper counts every chunk before
    application code sees it, so parsers and endpoints cannot be induced to
    consume an unbounded body.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_request_body_size: int | None = None,
        max_upload_size: int | None = None,
    ) -> None:
        self.app = app
        self.max_request_body_size = (
            settings.MAX_REQUEST_BODY_SIZE if max_request_body_size is None else max_request_body_size
        )
        self.max_upload_size = settings.MAX_UPLOAD_SIZE if max_upload_size is None else max_upload_size

    @staticmethod
    async def _send_error(scope: Scope, receive: Receive, send: Send, message: str, status_code: int) -> None:
        await Response(
            message,
            status_code=status_code,
            media_type="text/plain",
            headers={"Connection": "close"},
        )(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_type = headers.get(b"content-type", b"").decode("latin-1").lower()
        max_size = self.max_upload_size if "multipart/form-data" in content_type else self.max_request_body_size
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                await self._send_error(scope, receive, send, "Invalid Content-Length", 400)
                return
            if declared_size < 0:
                await self._send_error(scope, receive, send, "Invalid Content-Length", 400)
                return
            if declared_size > max_size:
                await self._send_error(scope, receive, send, "Request body too large", 413)
                return

        bytes_received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal bytes_received
            message = await receive()
            if message["type"] == "http.request":
                bytes_received += len(message.get("body", b""))
                if bytes_received > max_size:
                    raise _RequestBodyTooLarge()
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            if response_started:
                logger.warning("Request body limit exceeded after response started for %s", scope.get("path", ""))
                return
            await self._send_error(scope, receive, send, "Request body too large", 413)


class AdminIPAllowlistMiddleware(BaseHTTPMiddleware):
    """Restrict admin panel access to configured IP addresses."""

    async def dispatch(self, request: Request, call_next):
        allowlist_str = settings.ADMIN_IP_ALLOWLIST

        # Skip if allowlist is empty (disabled)
        if not allowlist_str or not allowlist_str.strip():
            return await call_next(request)

        # Only apply to admin routes
        path = request.url.path
        if not (path.startswith(("/api/admin", "/api/v1/admin")) or path == "/admin"):
            return await call_next(request)

        # Parse allowlist
        allowed_networks = []
        for entry in allowlist_str.split(","):
            entry = entry.strip()
            if not entry:
                continue
            try:
                allowed_networks.append(_ipaddress.ip_network(entry, strict=False))
            except ValueError:
                logger.warning("Ignoring invalid ADMIN_IP_ALLOWLIST entry: %s", entry)

        if not allowed_networks:
            logger.error("ADMIN_IP_ALLOWLIST is set but contains no valid networks; denying admin request")
            return JSONResponse(
                {"detail": "Access denied: invalid admin IP allowlist"},
                status_code=403,
            )

        # Check client IP
        client_ip = request.client.host if request.client else None
        if not client_ip:
            return JSONResponse(
                {"detail": "Access denied"},
                status_code=403,
            )

        try:
            client_addr = _ipaddress.ip_address(client_ip)
            if any(client_addr in network for network in allowed_networks):
                return await call_next(request)
        except ValueError:
            pass

        return JSONResponse(
            {"detail": "Access denied: IP not in allowlist"},
            status_code=403,
        )


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
                # Same-origin browser requests (fetch from UI to API on same host:port, e.g. Docker app:5000)
                try:
                    from urllib.parse import urlparse

                    if urlparse(origin).netloc == urlparse(str(request.base_url)).netloc:
                        allowed = True
                except Exception:
                    pass
                if not allowed:
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

        # --- CSRF Protection (Double-Submit Cookie) ---
        csrf_exempt_paths = {
            "/api/v1/auth/token",
            "/api/v1/auth/setup",
        }
        if request.method in ("POST", "PUT", "DELETE", "PATCH") and request.url.path not in csrf_exempt_paths:
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
            headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
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

        # Set the double-submit CSRF cookie for browser clients on any safe request that
        # lacks it. Covering API GETs (e.g. the SPA's /auth/me session probe) means the SPA
        # self-bootstraps CSRF regardless of whether the shell is served by FastAPI (prod) or
        # the Vite dev server (dev) — no dependency on a server-rendered page being hit first.
        if request.method in ("GET", "HEAD") and "csrf_token" not in request.cookies:
            csrf_tok = secrets.token_urlsafe(32)
            response.set_cookie(
                "csrf_token",
                csrf_tok,
                httponly=False,
                secure=not settings.DEBUG,
                samesite="lax",
                max_age=86400,
            )

        return response
