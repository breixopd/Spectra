"""Settings management service — business logic extracted from UI router."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import SettingsUpdateRequest
from app.core.config import settings
from app.services.system.runtime_settings import (
    build_runtime_ai_config_from_payload,
    get_resolved_runtime_ai_config_snapshot,
    get_runtime_ai_config_from_settings,
    hydrate_runtime_settings_from_db,
    serialize_runtime_ai_config_values,
    upsert_system_config_values,
)

logger = logging.getLogger(__name__)

_SETTINGS_LOCK = asyncio.Lock()


def public_ai_provider(provider: str | None) -> str:
    """Normalise raw provider string to the public-facing label."""
    normalized = (provider or "litellm").strip().lower()
    if normalized == "ollama":
        return "ollama"
    return "litellm"


def get_sandbox_status() -> dict:
    """Get sandbox pool availability status for the settings page."""
    try:
        from app.services.tools.sandbox import get_sandbox_pool

        pool = get_sandbox_pool()
        if pool and pool.available:
            return {"available": True, "message": "Docker connected"}
        return {"available": False, "message": "Docker not accessible"}
    except (ImportError, RuntimeError):
        return {"available": False, "message": "Sandbox pool not initialized"}


def _collect_general_db_settings(
    data: SettingsUpdateRequest,
    fields_set: set[str],
) -> dict[str, tuple[str, bool]]:
    """Map general (non-AI) request fields to DB key/value tuples."""
    mapping: list[tuple[str, str, str, bool]] = [
        ("log_level", "LOG_LEVEL", "str", False),
        ("plugin_safe_mode", "PLUGIN_SAFE_MODE", "bool", False),
        ("connect_back_host", "CONNECT_BACK_HOST", "str", False),
        ("require_approval", "REQUIRE_APPROVAL", "bool", False),
        ("fully_automated", "FULLY_AUTOMATED", "bool", False),
        ("notification_webhook", "NOTIFICATION_WEBHOOK", "nullable", False),
        ("embedding_model", "EMBEDDING_MODEL", "nullable", False),
        ("embedding_api_key", "EMBEDDING_API_KEY", "str", True),
        ("embedding_api_base_url", "EMBEDDING_API_BASE_URL", "nullable", False),
        ("platform_domain", "PLATFORM_DOMAIN", "nullable", False),
        ("platform_base_url", "PLATFORM_BASE_URL", "nullable", False),
        ("platform_exposed", "PLATFORM_EXPOSED", "bool", False),
        ("sandbox_max_containers", "SANDBOX_MAX_CONTAINERS", "int", False),
        ("sandbox_memory_limit", "SANDBOX_MEMORY_LIMIT", "str", False),
        ("sandbox_cpu_shares", "SANDBOX_CPU_SHARES", "int", False),
        ("sandbox_max_lifetime", "SANDBOX_MAX_LIFETIME", "int", False),
        ("sandbox_resource_tiers", "SANDBOX_RESOURCE_TIERS", "str", False),
        ("sandbox_network_isolation", "SANDBOX_NETWORK_ISOLATION", "bool", False),
        ("sandbox_idle_timeout", "SANDBOX_IDLE_TIMEOUT", "int", False),
        ("sandbox_heartbeat_interval", "SANDBOX_HEARTBEAT_INTERVAL", "int", False),
        ("sandbox_per_user_limit", "SANDBOX_PER_USER_LIMIT", "int", False),
        ("sandbox_default_priority", "SANDBOX_DEFAULT_PRIORITY", "int", False),
        ("sandbox_oom_escalation_enabled", "SANDBOX_OOM_ESCALATION_ENABLED", "bool", False),
        ("sandbox_warm_pool_enabled", "SANDBOX_WARM_POOL_ENABLED", "bool", False),
        ("sandbox_warm_pool_size", "SANDBOX_WARM_POOL_SIZE", "int", False),
        ("sandbox_auto_build_image", "SANDBOX_AUTO_BUILD_IMAGE", "bool", False),
        ("sandbox_image_scan_enabled", "SANDBOX_IMAGE_SCAN_ENABLED", "bool", False),
        ("sandbox_image_scan_block_critical", "SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL", "bool", False),
        ("sandbox_orchestrator_url", "SANDBOX_ORCHESTRATOR_URL", "nullable", False),
        ("sandbox_orchestrator_timeout", "SANDBOX_ORCHESTRATOR_TIMEOUT", "int", False),
        ("s3_endpoint_url", "S3_ENDPOINT_URL", "str", False),
        ("s3_access_key", "S3_ACCESS_KEY", "str", True),
        ("s3_secret_key", "S3_SECRET_KEY", "str", True),
        ("s3_region", "S3_REGION", "str", False),
    ]
    result: dict[str, tuple[str, bool]] = {}
    for field_name, db_key, conv, is_secret in mapping:
        if field_name not in fields_set:
            continue
        value = getattr(data, field_name, None)
        if conv == "nullable":
            result[db_key] = (value or "", is_secret)
        elif value is None:
            continue
        elif conv == "bool":
            result[db_key] = (str(value).lower(), is_secret)
        elif conv == "int":
            result[db_key] = (str(value), is_secret)
        else:
            result[db_key] = (str(value), is_secret)
    return result


_AI_FIELD_NAMES = frozenset({
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
})


def _collect_ai_db_settings(
    data: SettingsUpdateRequest,
    fields_set: set[str],
) -> dict[str, tuple[str, bool]]:
    """Map AI-related request fields to DB key/value tuples."""
    if not _AI_FIELD_NAMES.intersection(fields_set):
        return {}

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
    return serialize_runtime_ai_config_values(runtime_ai_config)


async def apply_settings_update(
    data: SettingsUpdateRequest,
    db: AsyncSession,
) -> dict[str, str]:
    """Persist settings update atomically.  Returns a status dict."""
    async with _SETTINGS_LOCK:
        fields_set = data.model_fields_set
        db_settings = _collect_general_db_settings(data, fields_set)
        db_settings.update(_collect_ai_db_settings(data, fields_set))

        await upsert_system_config_values(db, db_settings)
        await db.commit()
        await hydrate_runtime_settings_from_db(db, persist_normalized=True, commit=True)

    return {"status": "updated", "message": "Settings updated and saved"}


def get_current_settings() -> dict[str, Any]:
    """Return the full settings snapshot for the GET /api/settings endpoint."""
    from app.services.ai.router import PROVIDER_PRESETS

    resolved_ai = get_resolved_runtime_ai_config_snapshot(settings_obj=settings)
    provider = public_ai_provider(
        resolved_ai.get("default_route", {}).get("provider") or settings.AI_PROVIDER
    )

    return {
        "ai_provider": provider,
        "llm_model": settings.LLM_MODEL,
        "llm_api_base_url": settings.LLM_API_BASE_URL,
        "ollama_host": settings.OLLAMA_HOST,
        "ollama_model": settings.OLLAMA_MODEL,
        "ollama_enabled": settings.OLLAMA_ENABLED,
        "log_level": settings.LOG_LEVEL,
        "plugin_safe_mode": settings.PLUGIN_SAFE_MODE,
        "connect_back_host": settings.CONNECT_BACK_HOST,
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
        "sandbox_max_containers": settings.SANDBOX_MAX_CONTAINERS,
        "sandbox_memory_limit": settings.SANDBOX_MEMORY_LIMIT,
        "sandbox_cpu_shares": settings.SANDBOX_CPU_SHARES,
        "sandbox_max_lifetime": settings.SANDBOX_MAX_LIFETIME,
        "sandbox_available": get_sandbox_status(),
        "sandbox_resource_tiers": settings.SANDBOX_RESOURCE_TIERS,
        "sandbox_network_isolation": settings.SANDBOX_NETWORK_ISOLATION,
        "sandbox_idle_timeout": settings.SANDBOX_IDLE_TIMEOUT,
        "sandbox_heartbeat_interval": settings.SANDBOX_HEARTBEAT_INTERVAL,
        "sandbox_per_user_limit": settings.SANDBOX_PER_USER_LIMIT,
        "sandbox_default_priority": settings.SANDBOX_DEFAULT_PRIORITY,
        "sandbox_oom_escalation_enabled": settings.SANDBOX_OOM_ESCALATION_ENABLED,
        "sandbox_warm_pool_enabled": settings.SANDBOX_WARM_POOL_ENABLED,
        "sandbox_warm_pool_size": settings.SANDBOX_WARM_POOL_SIZE,
        "sandbox_auto_build_image": settings.SANDBOX_AUTO_BUILD_IMAGE,
        "sandbox_image_scan_enabled": settings.SANDBOX_IMAGE_SCAN_ENABLED,
        "sandbox_image_scan_block_critical": settings.SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL,
        "sandbox_orchestrator_url": settings.SANDBOX_ORCHESTRATOR_URL,
        "sandbox_orchestrator_timeout": settings.SANDBOX_ORCHESTRATOR_TIMEOUT,
        "s3_endpoint_url": settings.S3_ENDPOINT_URL,
        "s3_region": settings.S3_REGION,
        "s3_configured": bool(settings.S3_ENDPOINT_URL),
        "embedding_model": settings.EMBEDDING_MODEL,
        "embedding_api_base_url": settings.EMBEDDING_API_BASE_URL,
        "provider_profiles": resolved_ai["profiles"],
        "provider_routing": resolved_ai["routing"],
        "provider_fallbacks": resolved_ai["fallbacks"],
        "resolved_ai": resolved_ai,
        "provider_presets": PROVIDER_PRESETS,
    }


async def get_ai_status_snapshot() -> dict[str, Any]:
    """Build the AI status response payload."""
    from app.services.ai.llm import get_global_llm_client

    client = await get_global_llm_client()
    is_healthy = await client.health_check()
    resolved_ai = get_resolved_runtime_ai_config_snapshot(settings_obj=settings)
    resolved_routing = {"default": resolved_ai["default_route"], **resolved_ai["tiers"]}
    provider = public_ai_provider(
        resolved_ai.get("default_route", {}).get("provider") or settings.AI_PROVIDER
    )

    return {
        "provider": provider,
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


async def test_llm_connection(
    provider: str | None,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
    ollama_host: str | None,
) -> dict[str, Any]:
    """Test connectivity to an LLM provider. Returns {success, error?}."""
    from app.services.ai.llm import get_llm_client

    try:
        resolved_model = model or ""
        resolved_base = base_url or ollama_host
        raw_provider = (provider or "litellm").strip().lower()

        if (raw_provider == "ollama" or ollama_host) and not resolved_model.startswith("ollama/"):
            resolved_model = f"ollama/{resolved_model}"
            if not resolved_base:
                resolved_base = ollama_host or "http://localhost:11434"

        client = get_llm_client(
            provider="litellm",
            model=resolved_model,
            api_key=api_key,
            base_url=resolved_base,
        )

        response = await client.generate("Hello, are you there?", max_tokens=10)
        await client.close()

        if response:
            return {"success": True}
        return {"success": False, "error": "No response from LLM"}
    except (ConnectionError, TimeoutError, ValueError, RuntimeError, OSError):
        return {"success": False, "error": "Failed to communicate with LLM provider"}


async def load_settings_from_db() -> None:
    """Load settings from DB SystemConfig table, overriding in-memory values.

    Should be called during app startup so that DB values take precedence.
    """
    await hydrate_runtime_settings_from_db(persist_normalized=True, reset_caches=False)
