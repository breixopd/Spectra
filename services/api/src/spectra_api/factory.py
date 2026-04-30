"""Construct the Spectra FastAPI application."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import time

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.responses import Response as StarletteResponse

from app._meta.version import __version__
from app.auth.rate_limit import (
    RateLimits,
    limiter,
    rate_limit_exceeded_handler_sync,
)
from app.bootstrap.lifespan import lifespan
from app.bootstrap.logging_config import CorrelationIdMiddleware, configure_logging
from app.bootstrap.middleware import AdminIPAllowlistMiddleware, SecurityHeadersMiddleware
from app.bootstrap.templates import templates as shared_templates
from app.core.config import settings
from app.mission.core.websocket import manager
from app.telemetry.telemetry_middleware import TelemetryMiddleware
from spectra_api.errors import register_exception_handlers
from spectra_api.paths import static_directory
from spectra_api.routing import include_routers
from spectra_common.constants import SECONDS_PER_DAY

logger = logging.getLogger(__name__)

swagger_ui_params = {
    "syntaxHighlight.theme": "obsidian",
    "tryItOutEnabled": True,
    "displayRequestDuration": True,
    "defaultModelsExpandDepth": -1,
    "docExpansion": "none",
    "filter": True,
    "persistAuthorization": True,
    "deepLinking": True,
}

_TIMEOUT_EXEMPT_PREFIXES = ("/api/v1/export", "/ws")


def _is_timeout_exempt_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in _TIMEOUT_EXEMPT_PREFIXES) or (
        path.startswith("/api/v1/tools/") and path.endswith("/test")
    )


def _safe_rate_limit_handler(request: Request, exc: Exception) -> StarletteResponse:
    """Guard slowapi: only delegate real RateLimitExceeded; else 503."""
    if isinstance(exc, RateLimitExceeded):
        return rate_limit_exceeded_handler_sync(request, exc)
    logger.warning(
        "slowapi handler received non-RateLimitExceeded exception: %s: %s",
        type(exc).__name__,
        exc,
    )
    return JSONResponse({"error": "Service temporarily unavailable"}, status_code=503)


def create_app() -> FastAPI:
    configure_logging(log_format=settings.LOG_FORMAT, log_level=settings.LOG_LEVEL)

    app = FastAPI(
        title="Spectra Security Assessment API",
        description="AI-driven security assessment platform with MAKER Framework.",
        version=__version__,
        lifespan=lifespan,
        swagger_ui_parameters=swagger_ui_params,
        docs_url="/api/docs" if settings.DEBUG else None,
        redoc_url="/api/redoc" if settings.DEBUG else None,
        openapi_url="/api/openapi.json" if settings.DEBUG else None,
    )

    app.state.limiter = limiter
    app.state.limiter._rate_limit_exceeded_handler = _safe_rate_limit_handler  # type: ignore[attr-defined]
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler_sync)  # type: ignore[arg-type]
    app.add_middleware(SlowAPIMiddleware)

    register_exception_handlers(app, shared_templates)

    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Accept"],
        max_age=SECONDS_PER_DAY,
    )
    app.add_middleware(AdminIPAllowlistMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(TelemetryMiddleware)

    templates = shared_templates

    @app.middleware("http")
    async def maintenance_mode_check(request: Request, call_next):
        """Return 503 for authenticated UI when maintenance mode is on."""
        from app.core.config import settings as _settings

        path = request.url.path
        exempt = (
            path == "/"
            or path.startswith(
                ("/static", "/api/health", "/api/v1/health", "/api/admin", "/api/v1/auth", "/legal/")
            )
            or path == "/admin"
            or path == "/login"
        )
        if not exempt:
            is_maintenance = getattr(_settings, "MAINTENANCE_MODE", False)
            if is_maintenance:
                msg = (
                    getattr(_settings, "MAINTENANCE_MESSAGE", "")
                    or "We're performing scheduled maintenance. Please check back shortly."
                )
                if path.startswith("/api/"):
                    return JSONResponse({"detail": msg}, status_code=503)
                return HTMLResponse(
                    content=templates.get_template("errors/maintenance.html").render(message=msg),
                    status_code=503,
                )
        return await call_next(request)

    @app.middleware("http")
    async def request_timeout(request: Request, call_next):
        """Cancel requests that exceed REQUEST_TIMEOUT_SECONDS (returns 504)."""
        from spectra_api.errors import wants_html

        timeout = settings.REQUEST_TIMEOUT_SECONDS
        if timeout <= 0:
            return await call_next(request)
        path = request.url.path
        if _is_timeout_exempt_path(path):
            return await call_next(request)
        try:
            return await asyncio.wait_for(call_next(request), timeout=timeout)
        except TimeoutError:
            if wants_html(request):
                return HTMLResponse(
                    content=templates.get_template("errors/504.html").render(
                        detail="The request took too long to process. Please try again or reduce the scope of your request."
                    ),
                    status_code=504,
                )
            return JSONResponse(
                {"detail": "Request timeout"},
                status_code=504,
            )

    @app.middleware("http")
    async def limit_request_body_size(request: Request, call_next):
        """Reject bodies over MAX_REQUEST_BODY_SIZE (or MAX_UPLOAD_SIZE for multipart)."""
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                body_size = int(content_length)
            except ValueError:
                return StarletteResponse("Invalid Content-Length", status_code=400)
            content_type = request.headers.get("content-type", "")
            max_size = settings.MAX_UPLOAD_SIZE if "multipart/form-data" in content_type else settings.MAX_REQUEST_BODY_SIZE
            if body_size > max_size:
                return StarletteResponse("Request body too large", status_code=413)
        return await call_next(request)

    if settings.SERVICE_MODE in ("", "all", "api"):
        app.mount(
            "/static",
            StaticFiles(directory=str(static_directory()), html=True),
            name="static",
        )

    @app.get("/internal/metrics")
    @limiter.limit(RateLimits.INTERNAL_METRICS)
    async def internal_node_metrics(request: Request):
        """Return local system metrics. Requires service auth."""
        from app.services.scaling.node_metrics import collect_node_metrics

        auth = request.headers.get("X-Service-Auth", "")
        secret = settings.SERVICE_AUTH_SECRET.get_secret_value()
        if not auth or not secret or not hmac.compare_digest(auth, secret):
            raise HTTPException(status_code=401, detail="Unauthorized")
        mode = settings.SERVICE_MODE or "api"
        metrics = collect_node_metrics(mode)
        return metrics.to_dict()

    include_routers(app, settings.SERVICE_MODE)

    if settings.SERVICE_MODE in ("", "all", "api"):

        @app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket, token: str | None = None) -> None:
            from app.api.dependencies import validate_websocket_token

            ws_token = token
            if not ws_token:
                ws_token = websocket.cookies.get("access_token")
            user = await validate_websocket_token(ws_token)
            if not user:
                await websocket.close(code=4001, reason="Authentication required")
                logger.warning("WebSocket connection rejected: invalid or missing token")
                return

            websocket.state.user_id = str(user.id)
            await manager.connect(websocket, require_auth=False)
            await manager.join_room(websocket, f"user:{user.id}")
            logger.debug("WebSocket connected for user: %s", user.username)

            from spectra_common.constants import WS_MAX_MESSAGE_SIZE, WS_MAX_MESSAGES_PER_SECOND

            message_count = 0
            last_reset = time.time()

            try:
                while True:
                    data = await websocket.receive_text()

                    now = time.time()
                    if now - last_reset >= 1.0:
                        message_count = 0
                        last_reset = now
                    message_count += 1
                    if message_count > WS_MAX_MESSAGES_PER_SECOND:
                        await websocket.send_json({"type": "error", "message": "Rate limit exceeded"})
                        continue

                    if len(data) > WS_MAX_MESSAGE_SIZE:
                        logger.warning("WebSocket message too large from %s, ignoring", user.username)
                        continue

                    try:
                        message_json = json.loads(data)
                        if not isinstance(message_json, dict) or "type" not in message_json:
                            logger.warning("Invalid WebSocket message format from %s", user.username)
                            continue

                        msg_type = message_json.get("type")
                        if msg_type == "ping":
                            await websocket.send_text(json.dumps({"type": "pong"}))
                        else:
                            logger.debug("Received WS message type: %s", msg_type)
                    except json.JSONDecodeError:
                        logger.warning("Invalid JSON in WebSocket message from %s", user.username)

            except WebSocketDisconnect:
                await manager.disconnect(websocket)
                logger.debug("WebSocket client %s disconnected normally", user.username)
            except (OSError, RuntimeError, ConnectionError) as e:
                logger.warning("WebSocket error for %s: %s", user.username, e)
                await manager.disconnect(websocket)

    return app
