"""
UI router for serving the frontend dashboard.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import _is_admin_user, get_current_active_user
from app.api.schemas import LLMTestRequest, SettingsUpdateRequest
from app.core.config import settings
from app.core.database import async_session_maker, get_async_session
from app.core.rbac import Permission, require_permission
from app.models.user import User
from app.services.shell.session_manager import shell_manager
from app.services.system.settings_service import (
    apply_settings_update,
    get_ai_status_snapshot,
    get_current_settings,
    test_llm_connection,
)

router = APIRouter()
logger = logging.getLogger("spectra.ui")

# Templates directory
APP_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
templates.env.globals["app_name"] = settings.APP_NAME


def _get_ui_user(request: Request) -> dict | None:
    """Extract and validate user from cookie. Returns None if not authenticated."""
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        from app.core.security import decode_token, is_token_blacklisted
        if is_token_blacklisted(token):
            return None
        payload = decode_token(token)
        if payload and payload.get("sub"):
            return payload
    except Exception:
        logger.debug("UI token decode failed", exc_info=True)
    return None


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    """Serve the user profile and account management page."""
    if not _get_ui_user(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        "profile.html",
        {"request": request, "title": f"{settings.APP_NAME} | Account"},
    )


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    """Serve the setup page."""
    async with async_session_maker() as session:
        result = await session.execute(select(User.id).limit(1))
        if result.scalar_one_or_none():
            return RedirectResponse(url="/login")

    return templates.TemplateResponse(
        "setup.html",
        {"request": request, "title": f"{settings.APP_NAME} | Setup"},
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Serve the login page."""
    async with async_session_maker() as session:
        result = await session.execute(select(User.id).limit(1))
        if not result.scalar_one_or_none():
            return RedirectResponse(url="/setup")

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "title": f"{settings.APP_NAME} | Login"},
    )


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serve the main dashboard UI."""
    async with async_session_maker() as session:
        result = await session.execute(select(User.id).limit(1))
        if not result.scalar_one_or_none():
            return RedirectResponse(url="/setup")

    if not _get_ui_user(request):
        return RedirectResponse(url="/login")

    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "title": f"{settings.APP_NAME} | Dashboard"},
    )


@router.get("/targets", response_class=HTMLResponse)
async def targets_page(request: Request):
    """Serve the targets management page."""
    if not _get_ui_user(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        "targets.html",
        {"request": request, "title": f"{settings.APP_NAME} | Targets"},
    )


@router.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    """Serve the mission history page."""
    if not _get_ui_user(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        "history.html",
        {"request": request, "title": f"{settings.APP_NAME} | History"},
    )


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    """Serve the reports page."""
    if not _get_ui_user(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        "reports.html",
        {"request": request, "title": f"{settings.APP_NAME} | Reports"},
    )


@router.get("/overseer", response_class=HTMLResponse)
async def overseer_page(request: Request):
    """Serve the agent overseer page."""
    if not _get_ui_user(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        "overseer.html",
        {"request": request, "title": f"{settings.APP_NAME} | Agents"},
    )


@router.get("/toolbox", response_class=HTMLResponse)
async def toolbox_page(request: Request):
    """Serve the toolbox page."""
    user_payload = _get_ui_user(request)
    if not user_payload:
        return RedirectResponse(url="/login", status_code=303)
    is_admin = False
    username = user_payload.get("sub")
    if username:
        async with async_session_maker() as session:
            result = await session.execute(select(User).where(User.username == username))
            db_user = result.scalar_one_or_none()
            if db_user:
                is_admin = _is_admin_user(db_user)
    return templates.TemplateResponse(
        "toolbox.html",
        {"request": request, "title": f"{settings.APP_NAME} | Toolbox", "is_admin": is_admin},
    )


@router.get("/manual", response_class=HTMLResponse)
async def manual_tools_page(request: Request):
    """Serve the manual tools execution page."""
    if not _get_ui_user(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        "manual_tools.html",
        {"request": request, "title": f"{settings.APP_NAME} | Manual Tools"},
    )


@router.get("/toolbox/create", response_class=HTMLResponse)
async def plugin_creator_page(request: Request):
    """Serve the plugin creator page (admin only)."""
    user_payload = _get_ui_user(request)
    if not user_payload:
        return RedirectResponse(url="/login", status_code=303)
    username = user_payload.get("sub")
    if username:
        async with async_session_maker() as session:
            result = await session.execute(select(User).where(User.username == username))
            db_user = result.scalar_one_or_none()
            if not db_user or not _is_admin_user(db_user):
                return RedirectResponse(url="/toolbox", status_code=303)
    else:
        return RedirectResponse(url="/toolbox", status_code=303)
    return templates.TemplateResponse(
        "plugin_creator.html",
        {"request": request, "title": f"{settings.APP_NAME} | Plugin Creator"},
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Serve the settings page."""
    if not _get_ui_user(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        "settings.html",
        {"request": request, "title": f"{settings.APP_NAME} | Settings"},
    )


@router.get("/docs/api", response_class=HTMLResponse)
async def api_docs_page(request: Request):
    """Customer-facing API documentation."""
    if not _get_ui_user(request):
        return RedirectResponse(url="/login", status_code=303)

    from app.main import app as fastapi_app

    routes = []
    for route in fastapi_app.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            if route.path.startswith("/api/") and not route.path.startswith("/api/docs") and not route.path.startswith("/api/redoc") and not route.path.startswith("/api/openapi"):
                params = []
                if hasattr(route, "dependant"):
                    for param in getattr(route.dependant, "path_params", []):
                        params.append({"name": param.name, "in": "path", "required": True, "type": getattr(param.field_info, "annotation", str).__name__ if hasattr(param.field_info, "annotation") else "string"})
                    for param in getattr(route.dependant, "query_params", []):
                        params.append({"name": param.name, "in": "query", "required": param.required, "type": getattr(param.field_info, "annotation", str).__name__ if hasattr(param.field_info, "annotation") else "string"})
                routes.append({
                    "path": route.path,
                    "methods": sorted(route.methods - {"HEAD", "OPTIONS"}),
                    "name": route.name or "",
                    "description": (route.endpoint.__doc__ or "").strip(),
                    "tags": getattr(route, "tags", []),
                    "params": params,
                })

    groups: dict[str, list] = {}
    for r in routes:
        parts = r["path"].split("/")
        group = parts[2] if len(parts) > 2 else "general"
        groups.setdefault(group, []).append(r)

    return templates.TemplateResponse(
        "docs.html",
        {
            "request": request,
            "title": f"{settings.APP_NAME} | API Documentation",
            "route_groups": dict(sorted(groups.items())),
        },
    )


@router.get("/help", response_class=HTMLResponse)
async def help_page(request: Request):
    """Help center with guides and documentation."""
    if not _get_ui_user(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        "help.html",
        {"request": request, "title": f"{settings.APP_NAME} | Help Center"},
    )


@router.get("/observability", response_class=HTMLResponse)
async def observability_page(request: Request):
    """Serve the observability/monitoring page."""
    if not _get_ui_user(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        "observability.html",
        {"request": request, "title": f"{settings.APP_NAME} | Observability"},
    )


@router.get("/shell/{session_id}", response_class=HTMLResponse)
async def shell_page(request: Request, session_id: str):
    """Serve the interactive shell page."""
    if not _get_ui_user(request):
        return RedirectResponse(url="/login", status_code=303)
    session = await shell_manager.get_session(session_id)
    if not session:
        return HTMLResponse("Session not found or inactive", status_code=404)

    return templates.TemplateResponse(
        "shell.html",
        {
            "request": request,
            "title": f"Shell | {session.target}",
            "session_id": session_id,
            "target": session.target,
        },
    )


# ---------- API endpoints (thin delegation to settings_service) ----------


@router.post("/api/settings")
async def update_settings(
    data: SettingsUpdateRequest,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = require_permission(Permission.MANAGE_SETTINGS),
):
    """Update application settings."""
    return await apply_settings_update(data, db)


@router.get("/api/settings")
async def get_settings_api(
    _current_user: User = Depends(get_current_active_user),
):
    """Get current settings."""
    return get_current_settings()


@router.get("/api/ai/status")
async def get_ai_status(
    _current_user: User = Depends(get_current_active_user),
):
    """Get AI provider status and current model info."""
    return await get_ai_status_snapshot()


@router.post("/test-llm")
async def test_llm_endpoint(request: Request, payload: LLMTestRequest):
    """Test connection to LLM provider. Requires auth after setup."""
    async with async_session_maker() as session:
        result = await session.execute(select(User.id).limit(1))
        if result.scalar_one_or_none():
            token = request.headers.get("Authorization", "").replace("Bearer ", "")
            if not token:
                raise HTTPException(status_code=401, detail="Authentication required")
    return await test_llm_connection(
        provider=payload.provider,
        model=payload.model,
        api_key=payload.api_key,
        base_url=payload.base_url,
        ollama_host=payload.ollama_host,
    )
