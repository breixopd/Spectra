"""
UI router for serving the frontend dashboard.
"""

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_active_user
from app.api.schemas import LLMTestRequest, SettingsUpdateRequest
from app.core.config import settings
from app.core.database import async_session_maker, get_async_session
from app.core.rbac import Permission, require_permission
from app.models.user import User
from app.services.ai.llm import get_llm_client
from app.services.shell.session_manager import shell_manager
from app.services.system.runtime_settings import (
    build_runtime_ai_config_from_payload,
    get_resolved_runtime_ai_config_snapshot,
    get_runtime_ai_config_from_settings,
    hydrate_runtime_settings_from_db,
    serialize_runtime_ai_config_values,
    upsert_system_config_values,
)

router = APIRouter()

# Templates directory
APP_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
templates.env.globals["app_name"] = settings.APP_NAME


def _public_ai_provider(provider: str | None) -> str:
    normalized = (provider or "litellm").strip().lower()
    if normalized == "ollama":
        return "ollama"
    return "litellm"


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
        pass
    return None


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    """Serve the setup page."""
    # If already setup, redirect to login
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
    # If not setup, redirect to setup
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
    # If not setup, redirect to setup
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
    if not _get_ui_user(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        "toolbox.html",
        {"request": request, "title": f"{settings.APP_NAME} | Toolbox"},
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
    """Serve the plugin creator page."""
    if not _get_ui_user(request):
        return RedirectResponse(url="/login", status_code=303)
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
    # Verify session exists
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


SETTINGS_LOCK = asyncio.Lock()


@router.post("/api/settings")
async def update_settings(
    data: SettingsUpdateRequest,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = require_permission(Permission.MANAGE_SETTINGS),
):
    """Update application settings.

    Persists non-sensitive settings to runtime JSON file.
    Persists sensitive settings (API keys) to database with is_secret=True.
    Uses a lock to ensure atomic updates.
    """
    async with SETTINGS_LOCK:
        fields_set = data.model_fields_set
        db_settings: dict[str, tuple[str, bool]] = {}

        if "log_level" in fields_set and data.log_level is not None:
            db_settings["LOG_LEVEL"] = (data.log_level, False)
        if "plugin_safe_mode" in fields_set and data.plugin_safe_mode is not None:
            db_settings["PLUGIN_SAFE_MODE"] = (
                str(data.plugin_safe_mode).lower(),
                False,
            )
        if "connect_back_host" in fields_set and data.connect_back_host is not None:
            db_settings["CONNECT_BACK_HOST"] = (data.connect_back_host, False)
        if "tool_container_name" in fields_set:
            db_settings["TOOL_CONTAINER_NAME"] = (data.tool_container_name or "", False)
        if "require_approval" in fields_set and data.require_approval is not None:
            db_settings["REQUIRE_APPROVAL"] = (
                str(data.require_approval).lower(),
                False,
            )
        if "fully_automated" in fields_set and data.fully_automated is not None:
            db_settings["FULLY_AUTOMATED"] = (
                str(data.fully_automated).lower(),
                False,
            )
        if "notification_webhook" in fields_set:
            db_settings["NOTIFICATION_WEBHOOK"] = (
                data.notification_webhook or "",
                False,
            )
        if "embedding_provider" in fields_set:
            db_settings["EMBEDDING_PROVIDER"] = (data.embedding_provider or "", False)
        if "embedding_model" in fields_set:
            db_settings["EMBEDDING_MODEL"] = (data.embedding_model or "", False)
        if "platform_domain" in fields_set:
            db_settings["PLATFORM_DOMAIN"] = (data.platform_domain or "", False)
        if "platform_base_url" in fields_set:
            db_settings["PLATFORM_BASE_URL"] = (data.platform_base_url or "", False)
        if "platform_exposed" in fields_set and data.platform_exposed is not None:
            db_settings["PLATFORM_EXPOSED"] = (
                str(data.platform_exposed).lower(),
                False,
            )

        ai_field_names = {
            "ai_provider",
            "llm_api_key",
            "llm_api_base_url",
            "llm_model",
            "ollama_host",
            "ollama_model",
            "ollama_enabled",
            "provider_profiles",
            "provider_routing",
            "provider_fallbacks",
            "llm_tier1_model",
            "llm_tier2_model",
            "llm_tier3_model",
        }
        if ai_field_names.intersection(fields_set):
            runtime_ai_config = build_runtime_ai_config_from_payload(
                base_config=get_runtime_ai_config_from_settings(settings),
                provider_profiles=(
                    {
                        name: profile.model_dump(exclude_none=True)
                        for name, profile in data.provider_profiles.items()
                    }
                    if data.provider_profiles is not None
                    else None
                ),
                provider_routing=(
                    data.provider_routing.as_dict()
                    if data.provider_routing is not None
                    else None
                ),
                provider_fallbacks=(
                    data.provider_fallbacks.as_dict()
                    if data.provider_fallbacks is not None
                    else None
                ),
                legacy_provider=(
                    data.ai_provider if "ai_provider" in fields_set else None
                ),
                legacy_model=(data.llm_model if "llm_model" in fields_set else None),
                legacy_api_key=(
                    data.llm_api_key if "llm_api_key" in fields_set else None
                ),
                legacy_api_base_url=(
                    data.llm_api_base_url if "llm_api_base_url" in fields_set else None
                ),
                legacy_ollama_host=(
                    data.ollama_host if "ollama_host" in fields_set else None
                ),
                legacy_ollama_model=(
                    data.ollama_model if "ollama_model" in fields_set else None
                ),
                legacy_ollama_enabled=(
                    data.ollama_enabled if "ollama_enabled" in fields_set else None
                ),
                legacy_tier_models={
                    "LLM_TIER1_MODEL": (
                        data.llm_tier1_model if "llm_tier1_model" in fields_set else None
                    ),
                    "LLM_TIER2_MODEL": (
                        data.llm_tier2_model if "llm_tier2_model" in fields_set else None
                    ),
                    "LLM_TIER3_MODEL": (
                        data.llm_tier3_model if "llm_tier3_model" in fields_set else None
                    ),
                },
            )
            db_settings.update(serialize_runtime_ai_config_values(runtime_ai_config))

        await upsert_system_config_values(db, db_settings)
        await db.commit()
        await hydrate_runtime_settings_from_db(
            db,
            persist_normalized=True,
            commit=True,
        )
        settings.save_runtime_settings()

    return {"status": "updated", "message": "Settings updated and saved"}


@router.get("/api/settings")
async def get_settings_api(
    _current_user: User = Depends(get_current_active_user),
):
    """Get current settings."""
    from app.services.ai.router import PROVIDER_PRESETS

    resolved_ai = get_resolved_runtime_ai_config_snapshot(settings_obj=settings)
    public_provider = _public_ai_provider(
        resolved_ai.get("default_route", {}).get("provider") or settings.AI_PROVIDER
    )

    return {
        "ai_provider": public_provider,
        "llm_model": settings.LLM_MODEL,
        "llm_api_base_url": settings.LLM_API_BASE_URL,
        "ollama_host": settings.OLLAMA_HOST,
        "ollama_model": settings.OLLAMA_MODEL,
        "ollama_enabled": settings.OLLAMA_ENABLED,
        "log_level": settings.LOG_LEVEL,
        "plugin_safe_mode": settings.PLUGIN_SAFE_MODE,
        "connect_back_host": settings.CONNECT_BACK_HOST,
        "tool_container_name": settings.TOOL_CONTAINER_NAME,
        "require_approval": settings.REQUIRE_APPROVAL,
        "fully_automated": settings.FULLY_AUTOMATED,
        "llm_api_key_configured": bool(settings.LLM_API_KEY.get_secret_value()),
        "notification_webhook": settings.NOTIFICATION_WEBHOOK or "",
        "llm_tier1_model": settings.LLM_TIER1_MODEL,
        "llm_tier2_model": settings.LLM_TIER2_MODEL,
        "llm_tier3_model": settings.LLM_TIER3_MODEL,
        "platform_domain": settings.PLATFORM_DOMAIN,
        "platform_base_url": settings.PLATFORM_BASE_URL,
        "platform_exposed": settings.PLATFORM_EXPOSED,
        "embedding_provider": settings.EMBEDDING_PROVIDER,
        "embedding_model": settings.EMBEDDING_MODEL,
        "provider_profiles": resolved_ai["profiles"],
        "provider_routing": resolved_ai["routing"],
        "provider_fallbacks": resolved_ai["fallbacks"],
        "resolved_ai": resolved_ai,
        "provider_presets": PROVIDER_PRESETS,
    }


@router.get("/api/ai/status")
async def get_ai_status(
    _current_user: User = Depends(get_current_active_user),
):
    """Get AI provider status and current model info."""
    from app.services.ai.llm import get_global_llm_client

    client = await get_global_llm_client()
    is_healthy = await client.health_check()
    resolved_ai = get_resolved_runtime_ai_config_snapshot(settings_obj=settings)
    resolved_routing = {"default": resolved_ai["default_route"], **resolved_ai["tiers"]}
    public_provider = _public_ai_provider(
        resolved_ai.get("default_route", {}).get("provider") or settings.AI_PROVIDER
    )

    return {
        "provider": public_provider,
        "model": resolved_ai["default_route"].get("model"),
        "healthy": is_healthy,
        "default_profile": resolved_ai["default_profile"],
        "profiles": resolved_ai["profiles"],
        "fallbacks": resolved_ai["fallbacks"],
        "resolved_routing": resolved_routing,
        "provider_info": {
            "litellm": {
                "label": "LiteLLM (Unified AI Gateway)",
                "base_url": settings.LLM_API_BASE_URL,
                "configured": bool(settings.LLM_API_KEY.get_secret_value()),
                "ollama_host": settings.OLLAMA_HOST,
                "ollama_model": settings.OLLAMA_MODEL,
            },
        },
    }


@router.post("/test-llm")
async def test_llm_connection(request: Request, payload: LLMTestRequest):
    """Test connection to LLM provider. Requires auth after setup."""
    # After setup is complete, require authentication
    async with async_session_maker() as session:
        result = await session.execute(select(User.id).limit(1))
        if result.scalar_one_or_none():
            # Setup is complete — require valid auth
            token = request.headers.get("Authorization", "").replace("Bearer ", "")
            if not token:
                raise HTTPException(status_code=401, detail="Authentication required")
    try:
        # All providers go through LiteLLM
        model = payload.model or ""
        base_url = payload.base_url or payload.ollama_host
        raw_provider = (payload.provider or "litellm").strip().lower()

        # Auto-prefix Ollama models for LiteLLM routing
        if (raw_provider == "ollama" or payload.ollama_host) and not model.startswith("ollama/"):
            model = f"ollama/{model}"
            if not base_url:
                base_url = payload.ollama_host or "http://localhost:11434"

        client = get_llm_client(
            provider="litellm",
            model=model,
            api_key=payload.api_key,
            base_url=base_url,
        )

        # Try a simple generation
        response = await client.generate("Hello, are you there?", max_tokens=10)
        await client.close()

        if response:
            return {"success": True}
        return {"success": False, "error": "No response from LLM"}

    except Exception:
        return {"success": False, "error": "Failed to communicate with LLM provider"}


async def load_settings_from_db() -> None:
    """Load settings from DB SystemConfig table, overriding in-memory values.

    Should be called AFTER load_runtime_settings() during app startup
    so that DB values take precedence over JSON file values.
    """
    await hydrate_runtime_settings_from_db(persist_normalized=True, reset_caches=False)
