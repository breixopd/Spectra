"""Settings management service — business logic extracted from UI router."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import SettingsUpdate
from app.core.config import settings
from app.services.system.runtime_ai_config import apply_ai_settings
from app.services.system.runtime_settings import (
    hydrate_runtime_settings_from_db,
    upsert_system_config_values,
)

logger = logging.getLogger(__name__)

_SETTINGS_LOCK = asyncio.Lock()


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
    data: SettingsUpdate,
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
        # AI Gateway
        ("tensorzero_gateway_url", "TENSORZERO_GATEWAY_URL", "str", False),
        ("tensorzero_api_key", "TENSORZERO_API_KEY", "str", True),
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


async def apply_settings_update(
    data: SettingsUpdate,
    db: AsyncSession,
) -> dict[str, str]:
    """Persist settings update atomically.  Returns a status dict."""
    async with _SETTINGS_LOCK:
        fields_set = data.model_fields_set
        db_settings = _collect_general_db_settings(data, fields_set)

        await upsert_system_config_values(db, db_settings)
        await db.commit()
        await hydrate_runtime_settings_from_db(db, persist_normalized=True, commit=True)

    return {"status": "updated", "message": "Settings updated and saved"}


def get_current_settings() -> dict[str, Any]:
    """Return the full settings snapshot for the GET /api/settings endpoint."""
    return {
        "tensorzero_gateway_url": settings.TENSORZERO_GATEWAY_URL,
        "tensorzero_api_key_configured": bool(settings.TENSORZERO_API_KEY),
        "llm_timeout": settings.LLM_TIMEOUT,
        "log_level": settings.LOG_LEVEL,
        "plugin_safe_mode": settings.PLUGIN_SAFE_MODE,
        "connect_back_host": settings.CONNECT_BACK_HOST,
        "require_approval": settings.REQUIRE_APPROVAL,
        "fully_automated": settings.FULLY_AUTOMATED,
        "notification_webhook": settings.NOTIFICATION_WEBHOOK or "",
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
    }


async def get_ai_status_snapshot() -> dict[str, Any]:
    """Build the AI status response payload."""
    from app.services.ai.llm import get_global_llm_client

    client = await get_global_llm_client()
    is_healthy = await client.health_check()

    return {
        "provider": "tensorzero",
        "gateway_url": settings.TENSORZERO_GATEWAY_URL,
        "healthy": is_healthy,
        "embedding_model": settings.EMBEDDING_MODEL,
        "timeout": settings.LLM_TIMEOUT,
    }


async def test_llm_connection(
    model: str | None = None,
) -> dict[str, Any]:
    """Test connectivity to TensorZero gateway. Returns {success, error?}."""
    from app.services.ai.llm import get_global_llm_client

    try:
        client = await get_global_llm_client()
        response = await client.generate("Hello, are you there?", max_tokens=10)
        await client.close()

        if response:
            return {"success": True}
        return {"success": False, "error": "No response from LLM"}
    except (ConnectionError, TimeoutError, ValueError, RuntimeError, OSError) as e:
        return {"success": False, "error": f"Failed to communicate with TensorZero gateway: {e}"}


async def load_settings_from_db() -> None:
    """Load settings from DB SystemConfig table, overriding in-memory values."""
    await hydrate_runtime_settings_from_db(persist_normalized=True, reset_caches=False)
