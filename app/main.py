"""Spectra Security Assessment Platform - Main FastAPI Application."""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.routers import (
    admin,
    auth,
    cve,
    exploits,
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
    vpn,
    wordlists,
)
from app.core.config import settings
from app.core.lifespan import lifespan
from app.core.logging_config import CorrelationIdMiddleware, configure_logging
from app.core.middleware import SecurityHeadersMiddleware
from app.core.rate_limit import limiter, rate_limit_exceeded_handler
from app.core.telemetry_middleware import TelemetryMiddleware
from app.core.websocket import manager
from app.version import __version__

# --- Logging Setup ---
configure_logging()
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
app = FastAPI(
    title="Spectra Security Assessment API",
    description="AI-driven security assessment platform with MAKER Framework.",
    version=__version__,
    lifespan=lifespan,
    swagger_ui_parameters=swagger_ui_params,
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url="/api/redoc" if settings.DEBUG else None,
    openapi_url="/api/openapi.json",
)


# --- Rate Limiting ---
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)  # type: ignore
app.add_middleware(SlowAPIMiddleware)

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Security Headers ---
app.add_middleware(SecurityHeadersMiddleware)

# --- Correlation ID ---
app.add_middleware(CorrelationIdMiddleware)

# --- HTTP Telemetry ---
app.add_middleware(TelemetryMiddleware)

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


@app.exception_handler(500)
async def server_error_handler(request: Request, exc: Exception) -> HTMLResponse | JSONResponse:
    logger.exception("Internal server error: %s", exc)
    if _wants_html(request):
        return HTMLResponse(
            content=_error_templates.get_template("errors/500.html").render(),
            status_code=500,
        )
    return JSONResponse({"detail": "Internal server error"}, status_code=500)

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
api_v1.include_router(system.router, tags=["System"])
api_v1.include_router(cve.router, tags=["CVE Intelligence"])
api_v1.include_router(wordlists.router, tags=["Wordlists"])
api_v1.include_router(pentest_sessions.router, tags=["Pentest Sessions"])
api_v1.include_router(manual_helpers.router, tags=["Manual Helpers"])
api_v1.include_router(shell.router, tags=["Shell"])
api_v1.include_router(vpn.router, tags=["VPN"])
app.include_router(api_v1)

# --- /api (deprecated alias — kept for backward compatibility) ---
app.include_router(health.router, prefix="/api", tags=["Health"], deprecated=True)
app.include_router(auth.router, prefix="/api/auth", tags=["Auth"], deprecated=True)
app.include_router(tools.router, prefix="/api", tags=["Tools"], deprecated=True)
app.include_router(missions.router, prefix="/api", tags=["Missions"], deprecated=True)
app.include_router(targets.router, prefix="/api", tags=["Targets"], deprecated=True)
app.include_router(findings.router, prefix="/api", tags=["Findings"], deprecated=True)
app.include_router(exploits.router, prefix="/api", tags=["Exploits"], deprecated=True)
app.include_router(observability.router, prefix="/api", tags=["Observability"], deprecated=True)
app.include_router(system.router, prefix="/api", tags=["System"], deprecated=True)
app.include_router(cve.router, prefix="/api", tags=["CVE Intelligence"], deprecated=True)
app.include_router(wordlists.router, prefix="/api", tags=["Wordlists"], deprecated=True)
app.include_router(pentest_sessions.router, prefix="/api", tags=["Pentest Sessions"], deprecated=True)
app.include_router(manual_helpers.router, prefix="/api", tags=["Manual Helpers"], deprecated=True)
app.include_router(shell.router, prefix="/api", tags=["Shell"], deprecated=True)
app.include_router(vpn.router, prefix="/api", tags=["VPN"], deprecated=True)

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

    try:
        while True:
            data = await websocket.receive_text()
            # Validate message size (DoS protection)
            if len(data) > 65536:  # 64KB max message size
                logger.warning(
                    "WebSocket message too large from %s, ignoring", user.username
                )
                continue

            try:
                message_json = json.loads(data)
                if not isinstance(message_json, dict) or "type" not in message_json:
                    logger.warning(
                        "Invalid WebSocket message format from %s", user.username
                    )
                    continue

                msg_type = message_json.get("type")
                if msg_type == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                else:
                    logger.debug("Received WS message type: %s", msg_type)
            except json.JSONDecodeError:
                logger.warning(
                    "Invalid JSON in WebSocket message from %s", user.username
                )

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
