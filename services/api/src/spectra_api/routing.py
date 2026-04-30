"""Mount API routers based on ``SERVICE_MODE``."""

from __future__ import annotations

import logging

from fastapi import APIRouter, FastAPI

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

logger = logging.getLogger(__name__)


def include_routers(app: FastAPI, mode: str | None = None) -> None:
    """Include routers based on ``SERVICE_MODE``.

    Modes ``""``, ``"all"``, and ``"api"`` load the full router set. Dedicated
    service modes only mount a minimal surface (e.g. health).
    """
    if mode is None:
        mode = settings.SERVICE_MODE
    _full_modes = ("", "all", "api")

    if mode in _full_modes:
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

        from app.api.mcp import router as mcp_router

        app.include_router(mcp_router)

        app.include_router(health.router, prefix="/api", tags=["Health"], include_in_schema=False)

        app.include_router(public.router, tags=["Public"])
        app.include_router(ui.router, tags=["UI"])
        app.include_router(admin.router, tags=["Admin"], include_in_schema=False)

    elif mode in ("ai", "worker", "scheduler"):
        app.include_router(health.router, prefix="/api", tags=["Health"])

    elif mode == "tools":
        api_v1 = APIRouter(prefix="/api/v1")
        api_v1.include_router(health.router, tags=["Health"])
        api_v1.include_router(tools.router, tags=["Tools"])
        app.include_router(api_v1)
        app.include_router(health.router, prefix="/api", tags=["Health"], include_in_schema=False)

    else:
        logger.warning("Unknown SERVICE_MODE %r — loading all routers as fallback", mode)
        include_routers(app, "all")
        return

    logger.info("Service mode: %s — routers loaded", mode or "all")
