"""Spectra Security Assessment Platform - Main FastAPI Application."""

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
    cve,
    exploits,
    export,
    findings,
    health,
    manual_helpers,
    metrics,
    missions,
    observability,
    pentest_sessions,
    public,
    shell,
    system,
    targets,
    tools,
    ui,
    vpn,
    wordlists,
)
from app.core.config import settings
from app.core.exceptions import SpectraError, get_status_code_for_exception
from app.core.lifespan import lifespan
from app.core.logging_config import CorrelationIdMiddleware, configure_logging
from app.core.middleware import SecurityHeadersMiddleware
from app.core.rate_limit import limiter, rate_limit_exceeded_handler
from app.core.telemetry_middleware import TelemetryMiddleware
from app.core.websocket import manager
from app.version import __version__

# --- Logging Setup ---
configure_logging(log_format=settings.LOG_FORMAT, log_level=settings.LOG_LEVEL)
logger = logging.getLogger("spectra")

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
# API v1 - current version, prefix: /api/v1/
app = FastAPI(
    title="Spectra Security Assessment API",
    description="AI-driven security assessment platform with MAKER Framework.",
    version=__version__,
    lifespan=lifespan,
    swagger_ui_parameters=swagger_ui_params,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)


# --- Rate Limiting ---
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)  # type: ignore
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
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Accept", "X-API-Key"],
)

# --- Security Headers ---
app.add_middleware(SecurityHeadersMiddleware)

# --- Correlation ID ---
app.add_middleware(CorrelationIdMiddleware)

# --- HTTP Telemetry ---
app.add_middleware(TelemetryMiddleware)

# --- Paths exempt from request timeout (long-running by design) ---
_TIMEOUT_EXEMPT_PREFIXES = ("/api/v1/export", "/ws")


# --- Request Timeout ---
@app.middleware("http")
async def request_timeout(request: Request, call_next):
    """Cancel requests that exceed REQUEST_TIMEOUT_SECONDS (returns 504)."""
    timeout = settings.REQUEST_TIMEOUT_SECONDS
    if timeout <= 0:
        return await call_next(request)
    path = request.url.path
    if any(path.startswith(p) for p in _TIMEOUT_EXEMPT_PREFIXES):
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


# --- Static Files ---
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


@app.exception_handler(404)
async def not_found_handler(request: Request, exc: Exception) -> HTMLResponse | JSONResponse:
    if _wants_html(request):
        return HTMLResponse(
            content=_error_templates.get_template("errors/404.html").render(),
            status_code=404,
        )
    return JSONResponse({"detail": "Not found"}, status_code=404)


@app.exception_handler(403)
async def forbidden_handler(request: Request, exc: Exception) -> HTMLResponse | JSONResponse:
    if _wants_html(request):
        return HTMLResponse(
            content=_error_templates.get_template("errors/403.html").render(),
            status_code=403,
        )
    return JSONResponse({"detail": "Forbidden"}, status_code=403)


@app.exception_handler(401)
async def unauthorized_handler(request: Request, exc: Exception) -> HTMLResponse | JSONResponse:
    if _wants_html(request):
        return HTMLResponse(
            content=_error_templates.get_template("errors/401.html").render(),
            status_code=401,
        )
    return JSONResponse({"detail": "Unauthorized"}, status_code=401)


@app.exception_handler(429)
async def rate_limit_handler(request: Request, exc: Exception) -> HTMLResponse | JSONResponse:
    if _wants_html(request):
        return HTMLResponse(
            content=_error_templates.get_template("errors/429.html").render(),
            status_code=429,
        )
    return JSONResponse({"detail": "Too many requests"}, status_code=429)


@app.exception_handler(400)
async def bad_request_handler(request: Request, exc: Exception) -> HTMLResponse | JSONResponse:
    if _wants_html(request):
        return HTMLResponse(
            content=_error_templates.get_template("errors/400.html").render(),
            status_code=400,
        )
    return JSONResponse({"detail": "Bad request"}, status_code=400)


@app.exception_handler(405)
async def method_not_allowed_handler(request: Request, exc: Exception) -> HTMLResponse | JSONResponse:
    if _wants_html(request):
        return HTMLResponse(
            content=_error_templates.get_template("errors/405.html").render(),
            status_code=405,
        )
    return JSONResponse({"detail": "Method not allowed"}, status_code=405)


@app.exception_handler(500)
async def server_error_handler(request: Request, exc: Exception) -> HTMLResponse | JSONResponse:
    logger.exception("Internal server error: %s", exc)
    if _wants_html(request):
        return HTMLResponse(
            content=_error_templates.get_template("errors/500.html").render(),
            status_code=500,
        )
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


@app.exception_handler(502)
async def bad_gateway_handler(request: Request, exc: Exception) -> HTMLResponse | JSONResponse:
    if _wants_html(request):
        return HTMLResponse(
            content=_error_templates.get_template("errors/502.html").render(),
            status_code=502,
        )
    return JSONResponse({"detail": "Bad gateway"}, status_code=502)


@app.exception_handler(503)
async def service_unavailable_handler(request: Request, exc: Exception) -> HTMLResponse | JSONResponse:
    if _wants_html(request):
        return HTMLResponse(
            content=_error_templates.get_template("errors/503.html").render(),
            status_code=503,
        )
    return JSONResponse({"detail": "Service unavailable"}, status_code=503)


# --- Include Routers ---

# --- API v1 (canonical versioned prefix) ---
api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(health.router, tags=["Health"])
api_v1.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_v1.include_router(tools.router, tags=["Tools"])
api_v1.include_router(missions.router, tags=["Missions"])
api_v1.include_router(targets.router, tags=["Targets"])
api_v1.include_router(findings.router, tags=["Findings"])
api_v1.include_router(exploits.router, tags=["Exploits"])
api_v1.include_router(observability.router, tags=["Observability"])
api_v1.include_router(export.router, tags=["Export"])
api_v1.include_router(system.router, tags=["System"])
api_v1.include_router(cve.router, tags=["CVE Intelligence"])
api_v1.include_router(wordlists.router, tags=["Wordlists"])
api_v1.include_router(pentest_sessions.router, tags=["Pentest Sessions"])
api_v1.include_router(manual_helpers.router, tags=["Manual Helpers"])
api_v1.include_router(shell.router, tags=["Shell"])
api_v1.include_router(vpn.router, tags=["VPN"])
app.include_router(api_v1)

# --- Prometheus metrics endpoint (top-level for scraper compatibility) ---
app.include_router(metrics.router, tags=["Metrics"])

# --- Non-versioned routes (UI pages, public, admin) ---
app.include_router(public.router, tags=["Public"])
app.include_router(ui.router, tags=["UI"])
app.include_router(admin.router, tags=["Admin"])


# --- WebSocket Endpoint ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str | None = None) -> None:
    """
    WebSocket endpoint for real-time communication.

    Handles bidirectional messaging between the server and connected clients.

    Authentication: Pass JWT token as query parameter ?token=<jwt>
    If no token provided or invalid, connection is rejected.
    """
    from app.api.dependencies import validate_websocket_token

    # Validate authentication
    user = await validate_websocket_token(token)
    if not user:
        await websocket.close(code=4001, reason="Authentication required")
        logger.warning("WebSocket connection rejected: invalid or missing token")
        return

    await manager.connect(websocket, require_auth=False)
    logger.debug("WebSocket connected for user: %s", user.username)

    # Rate limiting state
    MAX_MESSAGES_PER_SECOND = 10
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
            if message_count > MAX_MESSAGES_PER_SECOND:
                await websocket.send_json({"type": "error", "message": "Rate limit exceeded"})
                continue

            # Validate message size (DoS protection)
            if len(data) > 65536:  # 64KB max message size
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
    except Exception as e:
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
