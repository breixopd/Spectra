"""Serve the built React SPA from FastAPI (same-origin, no separate dev server in production)."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

# Runtime path in the API Docker image (see deploy/docker/Dockerfile.api).
DOCKER_SPA_DIST = Path("/app/spa")

# Prefixes owned by the API or the server-rendered marketing/SEO surface. Everything else
# under the root is a client-side route handled by the SPA. The public landing ("/") is a
# server-rendered route registered before this fallback, so route ordering keeps it SSR.
_SPA_EXCLUDED_PREFIXES = (
    "/api",
    "/static",
    "/assets",
    "/ws",
    "/internal",
    "/admin",
    "/legal",
    "/mcp",
    "/pricing",
    "/register",
    "/setup",
    "/forgot-password",
    "/reset-password",
    "/verify-email",
    "/changelog",
    "/status",
    "/security",
    "/sitemap.xml",
)


def spa_dist_directory() -> Path | None:
    """Resolve the Vite build output directory, if present."""
    pkg = Path(__file__).resolve().parent
    for base in (pkg, *pkg.parents):
        candidate = base / "apps" / "web" / "dist"
        if candidate.is_dir() and (candidate / "index.html").is_file():
            return candidate

    if DOCKER_SPA_DIST.is_dir() and (DOCKER_SPA_DIST / "index.html").is_file():
        return DOCKER_SPA_DIST

    return None


def _is_spa_fallback_path(path: str) -> bool:
    if path.startswith(_SPA_EXCLUDED_PREFIXES):
        return False
    # Skip dotted asset-like paths (e.g. /favicon.ico handled by StaticFiles mount when present).
    basename = path.rsplit("/", 1)[-1]
    return not ("." in basename and not basename.endswith(".html"))


def register_spa(app: FastAPI) -> None:
    """Mount built assets and register SPA index fallback routes."""
    dist_dir = spa_dist_directory()
    if dist_dir is None:
        logger.warning(
            "SPA build output not found (expected apps/web/dist or %s); skipping SPA mount. "
            "Run `npm run build` in apps/web (the API image builds it automatically).",
            DOCKER_SPA_DIST,
        )
        return

    assets_dir = dist_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="spa-assets")

    index_file = dist_dir / "index.html"

    @app.get("/favicon.svg", include_in_schema=False)
    async def spa_favicon() -> FileResponse:
        favicon = dist_dir / "favicon.svg"
        if favicon.is_file():
            return FileResponse(favicon, media_type="image/svg+xml")
        raise HTTPException(status_code=404)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(request: Request, full_path: str) -> HTMLResponse:
        if request.method not in ("GET", "HEAD"):
            raise HTTPException(status_code=405)
        path = f"/{full_path}" if full_path else "/"
        if not _is_spa_fallback_path(path):
            raise HTTPException(status_code=404)
        return HTMLResponse(index_file.read_text(encoding="utf-8"))

    logger.info("SPA mounted from %s", dist_dir)
