"""Mount API routers for the **Core API** (`spectra_api`) process only.

``SERVICE_MODE`` still appears on every container image (see Dockerfiles) so
shared settings like DB pool tuning in ``app.core.config`` can branch. **Only
this API stack** reads ``SERVICE_MODE`` for *router* selection: split deploys
use dedicated ASGI apps for AI / worker / scheduler (``spectra_ai.main``,
``spectra_worker``, ``spectra_scheduler``) — they never call ``include_routers``.

Router policy: ``""``, ``"all"``, and ``"api"`` mount the full API; any other
value is treated as misconfiguration and mounts **health only** (fail closed).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, FastAPI

from spectra_api.api.routers import (
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
    shell,
    system,
    targets,
    tools,
    user_settings,
    vpn,
    wordlists,
)
from spectra_api.ui import public
from spectra_common.config import settings

logger = logging.getLogger(__name__)

# ``SERVICE_MODE`` values that select the full Core API graph in this process.
# Other images set ``SERVICE_MODE`` for ``app.core.config`` only; they do not
# use ``include_routers``. Keep ``spectra_api.factory`` in sync by importing
# this constant instead of duplicating the tuple.
CORE_API_FULL_ROUTER_MODES: frozenset[str] = frozenset(("", "all", "api"))


def include_routers(app: FastAPI, mode: str | None = None) -> None:
    """Include routers for the Core API process.

    Modes ``""``, ``"all"``, and ``"api"`` load the full router set. Any other
    value mounts **health only** (fail closed). There are no separate
    ``ai``/``worker``/``scheduler`` router modes here — those services use
    their own FastAPI apps in ``services/*/``.
    """
    if mode is None:
        mode = settings.SERVICE_MODE

    if mode in CORE_API_FULL_ROUTER_MODES:
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

        from spectra_api.api.mcp import router as mcp_router

        app.include_router(mcp_router)

        app.include_router(health.router, prefix="/api", tags=["Health"], include_in_schema=False)

        app.include_router(public.router, tags=["Public"])
        app.include_router(admin.router, tags=["Admin"], include_in_schema=False)

    else:
        logger.error(
            "Unknown SERVICE_MODE %r — mounting health-only surface (fail closed). "
            "For this process, use '', 'all', or 'api'. (Other images set SERVICE_MODE "
            "for shared config only; they do not use spectra_api routing.)",
            mode,
        )
        app.include_router(health.router, prefix="/api", tags=["Health"])

    logger.info("Service mode: %s — routers loaded", mode or "all")
