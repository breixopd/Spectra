"""
UI router for serving the frontend dashboard.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import LLMTestRequest
from app.core.config import settings
from app.core.database import async_session_maker, get_async_session
from app.models.user import User
from app.services.ai.llm import get_llm_client
from app.services.shell.session_manager import shell_manager

router = APIRouter()

# Templates directory
APP_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


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
        {"request": request, "title": "Spectra | Setup"},
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
        {"request": request, "title": "Spectra | Login"},
    )


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serve the main dashboard UI."""
    # If not setup, redirect to setup
    async with async_session_maker() as session:
        result = await session.execute(select(User.id).limit(1))
        if not result.scalar_one_or_none():
            return RedirectResponse(url="/setup")

    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "title": "Spectra | War Room"},
    )


@router.get("/targets", response_class=HTMLResponse)
async def targets_page(request: Request):
    """Serve the targets management page."""
    return templates.TemplateResponse(
        "targets.html",
        {"request": request, "title": "Spectra | Targets"},
    )


@router.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    """Serve the mission history page."""
    return templates.TemplateResponse(
        "history.html",
        {"request": request, "title": "Spectra | Mission History"},
    )


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    """Serve the reports page."""
    return templates.TemplateResponse(
        "reports.html",
        {"request": request, "title": "Spectra | Reports"},
    )


@router.get("/overseer", response_class=HTMLResponse)
async def overseer_page(request: Request):
    """Serve the agent overseer page."""
    return templates.TemplateResponse(
        "overseer.html",
        {"request": request, "title": "Spectra | Overseer"},
    )


@router.get("/toolbox", response_class=HTMLResponse)
async def toolbox_page(request: Request):
    """Serve the toolbox page."""
    return templates.TemplateResponse(
        "toolbox.html",
        {"request": request, "title": "Spectra | Toolbox"},
    )


@router.get("/manual", response_class=HTMLResponse)
async def manual_tools_page(request: Request):
    """Serve the manual tools execution page."""
    return templates.TemplateResponse(
        "manual_tools.html",
        {"request": request, "title": "Spectra | Manual Tools"},
    )


@router.get("/toolbox/create", response_class=HTMLResponse)
async def plugin_creator_page(request: Request):
    """Serve the plugin creator page."""
    return templates.TemplateResponse(
        "plugin_creator.html",
        {"request": request, "title": "Spectra | Plugin Creator"},
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Serve the settings page."""
    return templates.TemplateResponse(
        "settings.html",
        {"request": request, "title": "Spectra | Settings"},
    )


@router.get("/observability", response_class=HTMLResponse)
async def observability_page(request: Request):
    """Serve the observability/monitoring page."""
    return templates.TemplateResponse(
        "observability.html",
        {"request": request, "title": "Spectra | Observability"},
    )


@router.get("/shell/{session_id}", response_class=HTMLResponse)
async def shell_page(request: Request, session_id: str):
    """Serve the interactive shell page."""
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


# Global lock for settings updates to prevent race conditions
import asyncio

SETTINGS_LOCK = asyncio.Lock()


class SettingsUpdate(BaseModel):
    ai_provider: str
    llm_api_key: str | None = None
    llm_api_base_url: str | None = None
    llm_model: str | None = None
    ollama_host: str | None = None
    ollama_model: str | None = None
    log_level: str
    plugin_safe_mode: bool
    connect_back_host: str = "spectra-app"
    tool_container_name: str | None = None
    require_approval: bool = False
    notification_webhook: str | None = None


@router.post("/api/settings")
async def update_settings(
    data: SettingsUpdate,
    db: AsyncSession = Depends(get_async_session),
):
    """Update application settings.

    Persists non-sensitive settings to runtime JSON file.
    Persists sensitive settings (API keys) to database with is_secret=True.
    Uses a lock to ensure atomic updates.
    """
    from sqlalchemy import select
    from app.models.config import SystemConfig

    async with SETTINGS_LOCK:
        # Update runtime settings
        settings.AI_PROVIDER = data.ai_provider
        settings.LOG_LEVEL = data.log_level
        settings.PLUGIN_SAFE_MODE = data.plugin_safe_mode
        settings.CONNECT_BACK_HOST = data.connect_back_host
        settings.TOOL_CONTAINER_NAME = data.tool_container_name
        settings.REQUIRE_APPROVAL = data.require_approval
        if data.notification_webhook is not None:
            settings.NOTIFICATION_WEBHOOK = data.notification_webhook or None

        if data.llm_api_key:
            settings.LLM_API_KEY = data.llm_api_key
            # Persist API key to database (not JSON file)
            stmt = select(SystemConfig).where(SystemConfig.key == "LLM_API_KEY")
            result = await db.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                existing.value = data.llm_api_key
            else:
                db.add(
                    SystemConfig(
                        key="LLM_API_KEY", value=data.llm_api_key, is_secret=True
                    )
                )

        if data.llm_api_base_url:
            settings.LLM_API_BASE_URL = data.llm_api_base_url
        if data.llm_model:
            settings.LLM_MODEL = data.llm_model
        if data.ollama_host:
            settings.OLLAMA_HOST = data.ollama_host
        if data.ollama_model:
            settings.OLLAMA_MODEL = data.ollama_model

        # Persist non-sensitive settings to JSON file
        settings.save_runtime_settings()

        # Commit DB changes (API key)
        await db.commit()

        # Reinitialize the global LLM client with new settings
        import app.services.ai.llm as llm_module
        from app.services.ai.llm import close_global_llm_client

        await close_global_llm_client()
        llm_module._global_llm_client = None  # Force re-creation on next use

    return {"status": "updated", "message": "Settings updated and saved"}


@router.get("/api/settings")
async def get_settings_api():
    """Get current settings."""
    from app.services.ai.router import PROVIDER_PRESETS

    return {
        "ai_provider": settings.AI_PROVIDER,
        "llm_model": settings.LLM_MODEL,
        "llm_api_base_url": settings.LLM_API_BASE_URL,
        "ollama_host": settings.OLLAMA_HOST,
        "ollama_model": settings.OLLAMA_MODEL,
        "log_level": settings.LOG_LEVEL,
        "plugin_safe_mode": settings.PLUGIN_SAFE_MODE,
        "connect_back_host": settings.CONNECT_BACK_HOST,
        "tool_container_name": settings.TOOL_CONTAINER_NAME,
        "require_approval": settings.REQUIRE_APPROVAL,
        "llm_api_key_configured": bool(settings.LLM_API_KEY),
        "notification_webhook": settings.NOTIFICATION_WEBHOOK or "",
        "provider_presets": PROVIDER_PRESETS,
    }


@router.get("/api/ai/status")
async def get_ai_status():
    """Get AI provider status and current model info."""
    from app.services.ai.llm import get_global_llm_client

    client = await get_global_llm_client()
    is_healthy = await client.health_check()

    return {
        "provider": settings.AI_PROVIDER,
        "model": settings.LLM_MODEL
        if settings.AI_PROVIDER == "api"
        else settings.OLLAMA_MODEL,
        "healthy": is_healthy,
        "provider_info": {
            "api": {
                "base_url": settings.LLM_API_BASE_URL,
                "configured": bool(settings.LLM_API_KEY),
            },
            "ollama": {
                "host": settings.OLLAMA_HOST,
                "model": settings.OLLAMA_MODEL,
            },
        },
    }


@router.post("/test-llm")
async def test_llm_connection(request: LLMTestRequest):
    """Test connection to LLM provider."""
    try:
        if request.provider == "ollama":
            client = get_llm_client(
                provider="ollama",
                host=request.ollama_host or "http://localhost:11434",
                model=request.model,
            )
        else:
            client = get_llm_client(
                provider="api",
                api_key=request.api_key,
                base_url=request.base_url,
                model=request.model,
            )

        # Try a simple generation
        response = await client.generate("Hello, are you there?", max_tokens=10)
        await client.close()

        if response:
            return {"success": True}
        return {"success": False, "error": "No response from LLM"}

    except Exception:
        return {"success": False, "error": "Failed to communicate with LLM provider"}
