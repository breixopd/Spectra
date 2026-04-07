"""Spectra Security Assessment Platform - Main FastAPI Application.

Core API service. Use ai_service.py or scheduler_service.py for dedicated services.
"""

import asyncio
import json
import logging
import time
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.responses import Response as StarletteResponse

from app.api.routers import (
    admin,
    auth,
    billing,
    cve,
    exploits,
    export,
    findings,
    health,
    manual_helpers,
    missions,
    observability,
    pentest_sessions,
    public,
    shell,
    system,
    targets,
    tools,
    ui,
    user_settings,
    vpn,
    wordlists,
)
from app.core.config import settings
from app.core.exceptions import SpectraError, get_status_code_for_exception
from app.core.lifespan import lifespan
from app.core.logging_config import CorrelationIdMiddleware, configure_logging
from app.core.middleware import AdminIPAllowlistMiddleware, SecurityHeadersMiddleware
from app.core.rate_limit import (
    limiter,
    rate_limit_exceeded_handler_sync,
)
from app.core.telemetry_middleware import TelemetryMiddleware
from app.core.websocket import manager
from app.version import __version__

# --- Logging Setup ---
configure_logging(log_format=settings.LOG_FORMAT, log_level=settings.LOG_LEVEL)
logger = logging.getLogger(__name__)

# --- Path Configuration ---
APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

# --- Swagger UI Customization ---
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

# --- FastAPI Application ---
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


# --- Rate Limiting ---
app.state.limiter = limiter
app.state.limiter._rate_limit_exceeded_handler = rate_limit_exceeded_handler_sync
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler_sync)  # type: ignore[arg-type]
app.add_middleware(SlowAPIMiddleware)


# --- Spectra Exception Handler ---
@app.exception_handler(SpectraError)
async def spectra_error_handler(request: Request, exc: SpectraError) -> JSONResponse:
    """Map SpectraError subclasses to appropriate HTTP responses."""
    status_code = get_status_code_for_exception(exc)
    return JSONResponse(exc.to_dict(), status_code=status_code)


# --- GZip Compression ---
app.add_middleware(GZipMiddleware, minimum_size=1000)

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Accept"],
    max_age=86400,
)

# --- Admin IP Allowlist ---
app.add_middleware(AdminIPAllowlistMiddleware)

# --- Security Headers ---
app.add_middleware(SecurityHeadersMiddleware)

# --- Correlation ID ---
app.add_middleware(CorrelationIdMiddleware)

# --- HTTP Telemetry ---
app.add_middleware(TelemetryMiddleware)


# --- Maintenance Mode ---
@app.middleware("http")
async def maintenance_mode_check(request: Request, call_next):
    """Return 503 for all authenticated pages when maintenance mode is on."""
    from app.services.system.runtime_settings import get_runtime_setting_value

    path = request.url.path
    exempt = (
        path == "/"
        or path.startswith("/static")
        or path.startswith("/api/health")
        or path.startswith("/api/admin")
        or path == "/admin"
        or path == "/login"
        or path.startswith("/api/auth")
        or path.startswith("/api/v1/auth")
        or path.startswith("/legal/")
    )
    if not exempt:
        try:
            is_maintenance = await get_runtime_setting_value("MAINTENANCE_MODE")
            if is_maintenance:
                if path.startswith("/api/"):
                    msg = await get_runtime_setting_value("MAINTENANCE_MESSAGE") or "Maintenance in progress"
                    return JSONResponse({"detail": msg}, status_code=503)
                else:
                    msg = (
                        await get_runtime_setting_value("MAINTENANCE_MESSAGE")
                        or "We're performing scheduled maintenance. Please check back shortly."
                    )
                    _maint_templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
                    return HTMLResponse(
                        content=_maint_templates.get_template("errors/maintenance.html").render(message=msg),
                        status_code=503,
                    )
        except (OSError, RuntimeError):
            pass  # If DB is down, don't block requests
    return await call_next(request)


# --- Paths exempt from request timeout (long-running by design) ---
_TIMEOUT_EXEMPT_PREFIXES = ("/api/v1/export", "/ws")


def _is_timeout_exempt_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in _TIMEOUT_EXEMPT_PREFIXES) or (
        path.startswith("/api/v1/tools/") and path.endswith("/test")
    )


# --- Request Timeout ---
@app.middleware("http")
async def request_timeout(request: Request, call_next):
    """Cancel requests that exceed REQUEST_TIMEOUT_SECONDS (returns 504)."""
    timeout = settings.REQUEST_TIMEOUT_SECONDS
    if timeout <= 0:
        return await call_next(request)
    path = request.url.path
    if _is_timeout_exempt_path(path):
        return await call_next(request)
    try:
        return await asyncio.wait_for(call_next(request), timeout=timeout)
    except TimeoutError:
        return JSONResponse(
            {"detail": "Request timeout"},
            status_code=504,
        )


# --- Request Body Size Limit ---
@app.middleware("http")
async def limit_request_body_size(request: Request, call_next):
    """Reject requests with bodies exceeding MAX_REQUEST_BODY_SIZE."""
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.MAX_REQUEST_BODY_SIZE:
        return StarletteResponse("Request body too large", status_code=413)
    response = await call_next(request)
    return response


# --- Static Files (only for api/all modes that serve UI) ---
if settings.SERVICE_MODE in ("", "all", "api"):
    app.mount(
        "/static",
        StaticFiles(directory=str(STATIC_DIR), html=True),
        name="static",
    )

# --- Custom Error Handlers ---
_error_templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and not request.url.path.startswith("/api/")


def _make_error_handler(status_code: int, default_detail: str, template: str, log: bool = False):
    async def handler(request: Request, exc: Exception) -> HTMLResponse | JSONResponse:
        if log:
            logger.exception("Internal server error: %s", exc)
        if status_code == 429 and request.url.path.startswith("/api/"):
            if isinstance(exc, RateLimitExceeded):
                return rate_limit_exceeded_handler_sync(request, exc)
            detail = getattr(exc, "detail", default_detail)
            exc_headers = getattr(exc, "headers", None)
            return JSONResponse(
                {"detail": detail},
                status_code=429,
                headers=exc_headers,
            )
        if _wants_html(request):
            return HTMLResponse(
                content=_error_templates.get_template(template).render(),
                status_code=status_code,
            )
        return JSONResponse({"detail": default_detail}, status_code=status_code)

    return handler


_ERROR_HANDLERS: list[tuple] = [
    (400, "Bad request", "errors/400.html"),
    (401, "Unauthorized", "errors/401.html"),
    (403, "Forbidden", "errors/403.html"),
    (404, "Not found", "errors/404.html"),
    (405, "Method not allowed", "errors/405.html"),
    (429, "Too many requests", "errors/429.html"),
    (500, "Internal server error", "errors/500.html", True),
    (502, "Bad gateway", "errors/502.html"),
    (503, "Service unavailable", "errors/503.html"),
]

for _entry in _ERROR_HANDLERS:
    app.exception_handler(_entry[0])(_make_error_handler(*_entry))

# --- Include Routers (conditional on SERVICE_MODE) ---


def _include_routers(app: FastAPI, mode: str) -> None:
    """Include routers based on SERVICE_MODE setting.

    Modes ``""``, ``"all"``, and ``"api"`` load the full router set so that
    behaviour is identical to the previous unconditional setup.  Dedicated
    service modes (``"ai"``, ``"worker"``, ``"scheduler"``) only mount a
    health endpoint to keep the container's attack surface minimal.
    """
    _full_modes = ("", "all", "api")

    if mode in _full_modes:
        # --- API v1 (canonical versioned prefix) ---
        api_v1 = APIRouter(prefix="/api/v1")
        api_v1.include_router(health.router, tags=["Health"])
        api_v1.include_router(auth.router, prefix="/auth", tags=["Auth"])
        api_v1.include_router(tools.router, tags=["Tools"])
        api_v1.include_router(missions.router, prefix="/missions", tags=["Missions"])
        api_v1.include_router(targets.router, tags=["Targets"])
        api_v1.include_router(findings.router, prefix="/findings", tags=["Findings"])
        api_v1.include_router(exploits.router, tags=["Exploits"])
        api_v1.include_router(observability.router, tags=["Observability"])
        api_v1.include_router(export.router, tags=["Export"])
        api_v1.include_router(system.router, tags=["System"])
        api_v1.include_router(cve.router, tags=["CVE Intelligence"])
        api_v1.include_router(wordlists.router, tags=["Wordlists"])
        api_v1.include_router(pentest_sessions.router, tags=["Pentest Sessions"])
        api_v1.include_router(manual_helpers.router, prefix="/helpers", tags=["Manual Helpers"])
        api_v1.include_router(shell.router, tags=["Shell"])
        api_v1.include_router(vpn.router, tags=["VPN"])
        api_v1.include_router(user_settings.router, tags=["User Settings"])
        api_v1.include_router(billing.router, tags=["Billing"])
        app.include_router(api_v1)

        # MCP server endpoint (API key auth, not user-session auth)
        from app.api.mcp import router as mcp_router

        app.include_router(mcp_router)

        # Non-versioned health endpoint for Docker/LB probes
        app.include_router(health.router, prefix="/api", tags=["Health"], include_in_schema=False)

        # Backward-compatible auth routes at /api/auth/* (canonical: /api/v1/auth/*)
        app.include_router(auth.router, prefix="/api/auth", tags=["Auth"], include_in_schema=False)

        # --- Non-versioned routes (UI pages, public, admin) ---
        app.include_router(public.router, tags=["Public"])
        app.include_router(ui.router, tags=["UI"])
        app.include_router(admin.router, tags=["Admin"])

    elif mode == "ai":
        app.include_router(health.router, prefix="/api", tags=["Health"])

    elif mode == "worker":
        app.include_router(health.router, prefix="/api", tags=["Health"])

    elif mode == "scheduler":
        app.include_router(health.router, prefix="/api", tags=["Health"])

    elif mode == "tools":
        api_v1 = APIRouter(prefix="/api/v1")
        api_v1.include_router(health.router, tags=["Health"])
        api_v1.include_router(tools.router, tags=["Tools"])
        app.include_router(api_v1)
        app.include_router(health.router, prefix="/api", tags=["Health"], include_in_schema=False)

    else:
        logger.warning("Unknown SERVICE_MODE %r — loading all routers as fallback", mode)
        _include_routers(app, "all")
        return

    logger.info("Service mode: %s — routers loaded", mode or "all")


_include_routers(app, settings.SERVICE_MODE)


# --- WebSocket Endpoint (only for api/all modes) ---
if settings.SERVICE_MODE in ("", "all", "api"):

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket, token: str | None = None) -> None:
        """
        WebSocket endpoint for real-time communication.

        Handles bidirectional messaging between the server and connected clients.

        Authentication: Pass JWT token as query parameter ?token=<jwt>
        If no token provided or invalid, connection is rejected.
        """
        from app.api.dependencies import validate_websocket_token

        # Validate authentication: prefer query-param token, fall back to cookie
        ws_token = token
        if not ws_token:
            ws_token = websocket.cookies.get("access_token")
        user = await validate_websocket_token(ws_token)
        if not user:
            await websocket.close(code=4001, reason="Authentication required")
            logger.warning("WebSocket connection rejected: invalid or missing token")
            return

        await manager.connect(websocket, require_auth=False)
        # Auto-join user-specific room for scoped event delivery
        await manager.join_room(websocket, f"user:{user.id}")
        logger.debug("WebSocket connected for user: %s", user.username)

        # Rate limiting state
        from app.core.constants import WS_MAX_MESSAGE_SIZE, WS_MAX_MESSAGES_PER_SECOND

        message_count = 0
        last_reset = time.time()

        try:
            while True:
                data = await websocket.receive_text()

                # Per-second message rate limiting
                now = time.time()
                if now - last_reset >= 1.0:
                    message_count = 0
                    last_reset = now
                message_count += 1
                if message_count > WS_MAX_MESSAGES_PER_SECOND:
                    await websocket.send_json({"type": "error", "message": "Rate limit exceeded"})
                    continue

                # Validate message size (DoS protection)
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


# --- Root route is handled by public.router (landing page) ---


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=5000,
        reload=settings.DEBUG,
        log_level="info",
    )
