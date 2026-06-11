"""
UI router for serving the frontend dashboard.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.routing import Route

from spectra_api.api.dependencies import (
    _is_admin_user,
    get_current_user,
    get_ui_user,
    require_feature,
)
from spectra_api.authz import Permission, has_permission
from spectra_api.services.system.settings_service import get_current_settings
from spectra_api.templates import templates
from spectra_billing.entitlements import ENTITLEMENT_ACTIVE_SUBSCRIPTION_STATUSES
from spectra_common.config import settings
from spectra_infra.shell.session_manager import shell_manager
from spectra_persistence.database import async_session_maker, get_async_session
from spectra_persistence.models.user import User
from spectra_system.runtime_settings import get_runtime_setting_bool, get_runtime_setting_str

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
        from spectra_persistence.models.plan import Plan, Subscription
        from spectra_persistence.models.user import User

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
    """Serve the setup page.

    Always reachable so operators can review TensorZero / platform fields on Docker
    deploys without being bounced to login. When users already exist, the admin
    password section is optional; saving updates ``/api/settings`` if the browser
    has an authenticated session with MANAGE_SETTINGS, otherwise the UI explains
    that you must log in first.
    """
    first_user: User | None = None
    async with async_session_maker() as session:
        has_row = await session.execute(select(User.id).limit(1))
        has_users = has_row.scalar_one_or_none() is not None
        if has_users:
            fu = await session.execute(select(User).order_by(User.id).limit(1))
            first_user = fu.scalar_one_or_none()

    snap = get_current_settings()
    allow_registration = await get_runtime_setting_bool("ALLOW_REGISTRATION", True)
    contact_email = await get_runtime_setting_str("CONTACT_EMAIL", "") or ""
    prefill = {
        "platform_base_url": (snap.get("platform_base_url") or "") or "",
        "app_name": settings.APP_NAME or "Spectra",
        "contact_email": contact_email,
        "allow_registration": allow_registration,
        "tensorzero_gateway_url": (snap.get("tensorzero_gateway_url") or settings.TENSORZERO_GATEWAY_URL or ""),
        "embedding_model": (snap.get("embedding_model") or settings.EMBEDDING_MODEL or ""),
        "sandbox_orchestrator_url": (snap.get("sandbox_orchestrator_url") or "") or "",
    }

    return templates.TemplateResponse(
        request,
        "setup.html",
        {
            "request": request,
            "title": f"{settings.APP_NAME} | Setup",
            "has_users": has_users,
            "prefill": prefill,
            "admin_username": first_user.username if first_user else "",
            "admin_email": first_user.email if first_user else "",
        },
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
    from spectra_mission.framework_loader import list_frameworks
    available_frameworks = list_frameworks()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "title": f"{settings.APP_NAME} | Dashboard",
            "user_features": user_features,
            "available_frameworks": available_frameworks,
        },
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

                for param in getattr(route.dependant, "path_params", []) or []:
                    params.append(
                        {
                            "name": param.name,
                            "in": "path",
                            "required": True,
                            "type": _type_name(param.field_info),
                        }
                    )
                for param in getattr(route.dependant, "query_params", []) or []:
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
        return templates.TemplateResponse(
            request,
            "errors/404.html",
            {"request": request, "detail": "Shell session not found or inactive."},
            status_code=404,
        )

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


