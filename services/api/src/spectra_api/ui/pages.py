"""
UI router for serving the frontend dashboard.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.routing import Route

from app.api.dependencies import (
    _is_admin_user,
    get_current_active_user,
    get_current_user,
    get_ui_user,
    require_feature,
)
from app.api.schemas.system import SettingsUpdate
from app.auth.rbac import Permission, has_permission, require_permission
from app.core.config import settings
from app.core.database import async_session_maker, get_async_session
from app.models.user import User
from app.services.billing.entitlements import ENTITLEMENT_ACTIVE_SUBSCRIPTION_STATUSES
from app.services.shell.session_manager import shell_manager
from app.services.system.settings_service import (
    apply_settings_update,
    get_ai_status_snapshot,
    get_current_settings,
)
from spectra_api.templates import templates

router = APIRouter()
logger = logging.getLogger(__name__)

templates.env.globals["get_nav_user"] = get_ui_user


async def _require_manage_settings_or_prebootstrap(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Allow gateway probe during install (no users yet); otherwise MANAGE_SETTINGS or superuser."""
    user_count = (await session.execute(select(func.count()).select_from(User))).scalar_one()
    if user_count == 0:
        return
    user = await get_current_user(request=request, session=session)
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")
    if user.is_superuser:
        return
    if not has_permission(user.role, Permission.MANAGE_SETTINGS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


async def _get_user_features_dict(username: str | None) -> dict[str, bool]:
    if not username:
        return {}
    try:
        from app.models.plan import Plan, Subscription
        from app.models.user import User

        async with async_session_maker() as session:
            user_result = await session.execute(select(User).where(User.username == username))
            db_user = user_result.scalar_one_or_none()
            if db_user and _is_admin_user(db_user):
                return {}

            result = await session.execute(
                select(Plan.features)
                .join(Subscription, Subscription.plan_id == Plan.id)
                .join(User, User.id == Subscription.user_id)
                .where(
                    Plan.is_active.is_(True),
                    User.username == username,
                    Subscription.status.in_(tuple(ENTITLEMENT_ACTIVE_SUBSCRIPTION_STATUSES)),
                )
                .limit(1)
            )
            features = result.scalar_one_or_none()
            if features and isinstance(features, dict):
                return {k: bool(v) for k, v in features.items()}
    except Exception:
        logger.debug("Failed to load user features dict", exc_info=True)
    return {}


async def _get_ui_db_user(username: str | None) -> User | None:
    if not username:
        return None
    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    """Serve the user profile and account management page."""
    if not await get_ui_user(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        request,
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
        request,
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

    if await get_ui_user(request):
        return RedirectResponse(url="/dashboard", status_code=302)

    return templates.TemplateResponse(
        request,
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

    user_payload = await get_ui_user(request)
    if not user_payload:
        return RedirectResponse(url="/login")

    user_features = await _get_user_features_dict(user_payload.get("sub"))
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"request": request, "title": f"{settings.APP_NAME} | Dashboard", "user_features": user_features},
    )


@router.get("/targets", response_class=HTMLResponse)
async def targets_page(request: Request):
    """Serve the targets management page."""
    user_payload = await get_ui_user(request)
    if not user_payload:
        return RedirectResponse(url="/login", status_code=303)
    user_features = await _get_user_features_dict(user_payload.get("sub"))
    return templates.TemplateResponse(
        request,
        "targets.html",
        {"request": request, "title": f"{settings.APP_NAME} | Targets", "user_features": user_features},
    )


@router.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    user_payload = await get_ui_user(request)
    if not user_payload:
        return RedirectResponse(url="/login", status_code=303)
    user_features = await _get_user_features_dict(user_payload.get("sub"))
    return templates.TemplateResponse(
        request,
        "history.html",
        {"request": request, "title": f"{settings.APP_NAME} | History", "user_features": user_features},
    )


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    user_payload = await get_ui_user(request)
    if not user_payload:
        return RedirectResponse(url="/login", status_code=303)
    user_features = await _get_user_features_dict(user_payload.get("sub"))
    return templates.TemplateResponse(
        request,
        "reports.html",
        {"request": request, "title": f"{settings.APP_NAME} | Reports", "user_features": user_features},
    )


@router.get("/overseer", response_class=HTMLResponse)
async def overseer_page(request: Request):
    """Serve the agent overseer page."""
    if not await get_ui_user(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        request,
        "overseer.html",
        {"request": request, "title": f"{settings.APP_NAME} | Agents"},
    )


@router.get("/toolbox", response_class=HTMLResponse)
async def toolbox_page(request: Request):
    """Serve the toolbox page."""
    user_payload = await get_ui_user(request)
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
        request,
        "toolbox.html",
        {"request": request, "title": f"{settings.APP_NAME} | Toolbox", "is_admin": is_admin},
    )


@router.get("/manual", response_class=HTMLResponse)
async def manual_tools_page(
    request: Request,
    _user: User = Depends(require_feature("manual_mode")),
):
    return templates.TemplateResponse(
        request,
        "manual_tools.html",
        {"request": request, "title": f"{settings.APP_NAME} | Manual Tools"},
    )


@router.get("/toolbox/create", response_class=HTMLResponse)
async def plugin_creator_page(request: Request):
    """Serve the plugin creator page (admin only)."""
    user_payload = await get_ui_user(request)
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
        request,
        "plugin_creator.html",
        {"request": request, "title": f"{settings.APP_NAME} | Plugin Creator"},
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Serve the settings page."""
    if not await get_ui_user(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"request": request, "title": f"{settings.APP_NAME} | Settings"},
    )


@router.get("/docs/api", response_class=HTMLResponse)
async def api_docs_page(
    request: Request,
    current_user: User = Depends(require_feature("api_access")),
):
    if not await get_ui_user(request):
        return RedirectResponse(url="/login", status_code=303)
    is_admin = _is_admin_user(current_user)

    fastapi_app = request.app

    routes = []
    for route in fastapi_app.routes:
        if not isinstance(route, Route):
            continue
        if (
            route.path.startswith("/api/")
            and not route.path.startswith("/api/docs")
            and not route.path.startswith("/api/redoc")
            and not route.path.startswith("/api/openapi")
        ):
            params = []
            if hasattr(route, "dependant"):

                def _type_name(fi):
                    ann = getattr(fi, "annotation", None)
                    if ann is None:
                        return "string"
                    return getattr(ann, "__name__", str(ann))

                for param in getattr(route.dependant, "path_params", []):  # type: ignore[union-attr]
                    params.append(
                        {
                            "name": param.name,
                            "in": "path",
                            "required": True,
                            "type": _type_name(param.field_info),
                        }
                    )
                for param in getattr(route.dependant, "query_params", []):  # type: ignore[union-attr]
                    params.append(
                        {
                            "name": param.name,
                            "in": "query",
                            "required": getattr(param, "required", False),
                            "type": _type_name(param.field_info),
                        }
                    )
            routes.append(
                {
                    "path": route.path,
                    "methods": sorted((route.methods or set()) - {"HEAD", "OPTIONS"}),
                    "name": route.name or "",
                    "description": (route.endpoint.__doc__ or "").strip(),
                    "tags": getattr(route, "tags", []),
                    "params": params,
                }
            )

    groups: dict[str, list] = {}
    for r in routes:
        parts = r["path"].split("/")
        group = parts[2] if len(parts) > 2 else "general"
        groups.setdefault(group, []).append(r)

    # Role-based filtering: hide admin/system routes from non-admin users
    if not is_admin:
        # Remove the admin group entirely
        groups.pop("admin", None)
        # Remove admin/system/observability routes from other groups
        _admin_segments = {"/admin/", "/system/", "/observability/"}
        for grp in list(groups):
            groups[grp] = [r for r in groups[grp] if not any(seg in r["path"] for seg in _admin_segments)]
            if not groups[grp]:
                del groups[grp]

    return templates.TemplateResponse(
        request,
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
    if not await get_ui_user(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        request,
        "help.html",
        {"request": request, "title": f"{settings.APP_NAME} | Help Center"},
    )


@router.get("/observability", response_class=HTMLResponse)
async def observability_page(request: Request):
    """Serve the observability/monitoring page."""
    user_payload = await get_ui_user(request)
    if not user_payload:
        return RedirectResponse(url="/login", status_code=303)
    user = await _get_ui_db_user(user_payload.get("sub"))
    if not user or not (_is_admin_user(user) or has_permission(user.role, Permission.MANAGE_SETTINGS)):
        return templates.TemplateResponse(
            request,
            "errors/403.html",
            {
                "request": request,
                "detail": "Observability is limited to administrators and users who can manage platform settings.",
            },
            status_code=403,
        )
    return templates.TemplateResponse(
        request,
        "observability.html",
        {"request": request, "title": f"{settings.APP_NAME} | Observability"},
    )


@router.get("/shell/{session_id}", response_class=HTMLResponse)
async def shell_page(request: Request, session_id: str):
    """Serve the interactive shell page."""
    if not await get_ui_user(request):
        return RedirectResponse(url="/login", status_code=303)
    session = await shell_manager.get_session(session_id)
    if not session:
        return HTMLResponse("Session not found or inactive", status_code=404)

    return templates.TemplateResponse(
        request,
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
    data: SettingsUpdate,
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
async def test_llm_connection(
    request: Request,
    _user: User = require_permission(Permission.MANAGE_SETTINGS),
):
    """Test TensorZero gateway connection."""
    import httpx

    gw_url = settings.TENSORZERO_GATEWAY_URL or "http://tensorzero:3000"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{gw_url}/health")
            if resp.status_code == 200:
                return {"status": "ok", "message": "TensorZero gateway is healthy"}
            return {"status": "error", "message": f"Gateway returned status {resp.status_code}"}
    except Exception as e:
        logger.warning("TensorZero gateway health check failed: %s", e)
        return {"status": "error", "message": "Cannot reach LLM gateway \u2014 check configuration"}


@router.post("/test-tz-gateway")
async def test_tz_gateway(
    request: Request,
    _access: None = Depends(_require_manage_settings_or_prebootstrap),
):
    """Test TensorZero gateway connection (setup page)."""
    import httpx

    body = await request.json()
    gw_url = body.get("gateway_url") or settings.TENSORZERO_GATEWAY_URL or "http://tensorzero:3000"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{gw_url}/health")
            if resp.status_code == 200:
                return {"success": True}
            return {"success": False, "error": f"Gateway returned status {resp.status_code}"}
    except Exception as e:
        logger.warning("TensorZero gateway test failed for %s: %s", gw_url, e)
        return {"success": False, "error": "Cannot reach LLM gateway \u2014 check URL and try again"}
