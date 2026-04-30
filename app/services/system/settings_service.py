"""Settings management service — business logic extracted from UI router."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.system import SettingsUpdate
from app.core.config import settings
from app.services.system.runtime_settings import (
    hydrate_runtime_settings_from_db,
    upsert_system_config_values,
)

logger = logging.getLogger(__name__)

_SETTINGS_LOCK = asyncio.Lock()

GeneralDbFieldSpec = tuple[str, str, str, bool]
SettingsSnapshotSpec = tuple[str, str, Callable[[Any], Any] | None]

_GENERAL_DB_FIELD_SPECS: tuple[GeneralDbFieldSpec, ...] = (
    ("maintenance_mode", "MAINTENANCE_MODE", "bool", False),
    ("maintenance_message", "MAINTENANCE_MESSAGE", "str", False),
    ("log_level", "LOG_LEVEL", "str", False),
    ("connect_back_host", "CONNECT_BACK_HOST", "str", False),
    ("shell_listen_host", "SHELL_LISTEN_HOST", "str", False),
    ("notification_webhook", "NOTIFICATION_WEBHOOK", "nullable", False),
    ("embedding_model", "EMBEDDING_MODEL", "nullable", False),
    ("embedding_api_key", "EMBEDDING_API_KEY", "str", True),
    ("embedding_api_base_url", "EMBEDDING_API_BASE_URL", "nullable", False),
    ("platform_domain", "PLATFORM_DOMAIN", "nullable", False),
    ("platform_base_url", "PLATFORM_BASE_URL", "nullable", False),
    ("platform_exposed", "PLATFORM_EXPOSED", "bool", False),
    ("payment_provider", "PAYMENT_PROVIDER", "str", False),
    ("stripe_publishable_key", "STRIPE_PUBLISHABLE_KEY", "nullable", False),
    ("stripe_secret_key", "STRIPE_SECRET_KEY", "str", True),
    ("stripe_webhook_secret", "STRIPE_WEBHOOK_SECRET", "str", True),
    ("crypto_payment_url", "CRYPTO_PAYMENT_URL", "nullable", False),
    ("crypto_payment_api_key", "CRYPTO_PAYMENT_API_KEY", "str", True),
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
    ("sandbox_image_scan_block_critical", "SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL", "bool", False),
    ("sandbox_orchestrator_url", "SANDBOX_ORCHESTRATOR_URL", "nullable", False),
    ("sandbox_orchestrator_timeout", "SANDBOX_ORCHESTRATOR_TIMEOUT", "int", False),
    ("s3_endpoint_url", "S3_ENDPOINT_URL", "str", False),
    ("s3_access_key", "S3_ACCESS_KEY", "str", True),
    ("s3_secret_key", "S3_SECRET_KEY", "str", True),
    ("s3_region", "S3_REGION", "str", False),
    ("tensorzero_gateway_url", "TENSORZERO_GATEWAY_URL", "str", False),
    ("tensorzero_api_key", "TENSORZERO_API_KEY", "str", True),
    # Auto-scaling
    ("autoscale_enabled", "AUTOSCALE_ENABLED", "bool", False),
    ("autoscale_worker_min", "AUTOSCALE_WORKER_MIN", "int", False),
    ("autoscale_worker_max", "AUTOSCALE_WORKER_MAX", "int", False),
    ("autoscale_api_min", "AUTOSCALE_API_MIN", "int", False),
    ("autoscale_api_max", "AUTOSCALE_API_MAX", "int", False),
    ("autoscale_ai_max", "AUTOSCALE_AI_MAX", "int", False),
    ("autoscale_queue_threshold", "AUTOSCALE_QUEUE_THRESHOLD", "int", False),
    ("autoscale_cooldown_secs", "AUTOSCALE_COOLDOWN_SECS", "int", False),
    ("autoscale_idle_secs", "AUTOSCALE_IDLE_SECS", "int", False),
    # Infrastructure monitoring
    ("infra_monitor_enabled", "INFRA_MONITOR_ENABLED", "bool", False),
)

_SETTINGS_SNAPSHOT_FIELDS_BEFORE_SANDBOX_STATUS: tuple[SettingsSnapshotSpec, ...] = (
    ("tensorzero_gateway_url", "TENSORZERO_GATEWAY_URL", None),
    ("tensorzero_api_key_configured", "TENSORZERO_API_KEY", bool),
    ("llm_timeout", "LLM_TIMEOUT", None),
    ("maintenance_mode", "MAINTENANCE_MODE", None),
    ("maintenance_message", "MAINTENANCE_MESSAGE", None),
    ("log_level", "LOG_LEVEL", None),
    ("connect_back_host", "CONNECT_BACK_HOST", None),
    ("shell_listen_host", "SHELL_LISTEN_HOST", None),
    ("notification_webhook", "NOTIFICATION_WEBHOOK", lambda value: value or ""),
    ("platform_domain", "PLATFORM_DOMAIN", None),
    ("platform_base_url", "PLATFORM_BASE_URL", None),
    ("platform_exposed", "PLATFORM_EXPOSED", None),
    ("payment_provider", "PAYMENT_PROVIDER", None),
    ("stripe_publishable_key", "STRIPE_PUBLISHABLE_KEY", None),
    ("stripe_secret_key_configured", "STRIPE_SECRET_KEY", bool),
    ("stripe_webhook_secret_configured", "STRIPE_WEBHOOK_SECRET", bool),
    ("crypto_payment_url", "CRYPTO_PAYMENT_URL", None),
    ("crypto_payment_configured", "CRYPTO_PAYMENT_API_KEY", bool),
    ("sandbox_max_containers", "SANDBOX_MAX_CONTAINERS", None),
    ("sandbox_memory_limit", "SANDBOX_MEMORY_LIMIT", None),
    ("sandbox_cpu_shares", "SANDBOX_CPU_SHARES", None),
    ("sandbox_max_lifetime", "SANDBOX_MAX_LIFETIME", None),
)

_SETTINGS_SNAPSHOT_FIELDS_AFTER_SANDBOX_STATUS: tuple[SettingsSnapshotSpec, ...] = (
    ("sandbox_resource_tiers", "SANDBOX_RESOURCE_TIERS", None),
    ("sandbox_network_isolation", "SANDBOX_NETWORK_ISOLATION", None),
    ("sandbox_idle_timeout", "SANDBOX_IDLE_TIMEOUT", None),
    ("sandbox_heartbeat_interval", "SANDBOX_HEARTBEAT_INTERVAL", None),
    ("sandbox_per_user_limit", "SANDBOX_PER_USER_LIMIT", None),
    ("sandbox_default_priority", "SANDBOX_DEFAULT_PRIORITY", None),
    ("sandbox_oom_escalation_enabled", "SANDBOX_OOM_ESCALATION_ENABLED", None),
    ("sandbox_image_scan_block_critical", "SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL", None),
    ("sandbox_orchestrator_url", "SANDBOX_ORCHESTRATOR_URL", None),
    ("sandbox_orchestrator_timeout", "SANDBOX_ORCHESTRATOR_TIMEOUT", None),
    ("s3_endpoint_url", "S3_ENDPOINT_URL", None),
    ("s3_region", "S3_REGION", None),
    ("s3_configured", "S3_ENDPOINT_URL", bool),
    ("embedding_model", "EMBEDDING_MODEL", None),
    ("embedding_api_base_url", "EMBEDDING_API_BASE_URL", None),
    # Auto-scaling
    ("autoscale_enabled", "AUTOSCALE_ENABLED", None),
    ("autoscale_worker_min", "AUTOSCALE_WORKER_MIN", None),
    ("autoscale_worker_max", "AUTOSCALE_WORKER_MAX", None),
    ("autoscale_api_min", "AUTOSCALE_API_MIN", None),
    ("autoscale_api_max", "AUTOSCALE_API_MAX", None),
    ("autoscale_ai_max", "AUTOSCALE_AI_MAX", None),
    ("autoscale_queue_threshold", "AUTOSCALE_QUEUE_THRESHOLD", None),
    ("autoscale_cooldown_secs", "AUTOSCALE_COOLDOWN_SECS", None),
    ("autoscale_idle_secs", "AUTOSCALE_IDLE_SECS", None),
    ("infra_monitor_enabled", "INFRA_MONITOR_ENABLED", None),
)


def _convert_general_db_value(value: Any, conversion: str) -> str | None:
    if conversion == "nullable":
        return value or ""
    if value is None:
        return None
    if conversion == "bool":
        return str(value).lower()
    return str(value)


def _build_settings_snapshot(fields: tuple[SettingsSnapshotSpec, ...]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    for response_key, settings_attr, transform in fields:
        value = getattr(settings, settings_attr, None)
        snapshot[response_key] = transform(value) if transform else value
    return snapshot


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
    result: dict[str, tuple[str, bool]] = {}
    for field_name, db_key, conversion, is_secret in _GENERAL_DB_FIELD_SPECS:
        if field_name not in fields_set:
            continue
        converted = _convert_general_db_value(getattr(data, field_name, None), conversion)
        if converted is None:
            continue
        result[db_key] = (converted, is_secret)
    return result


async def apply_settings_update(
    data: SettingsUpdate,
    db: AsyncSession,
) -> dict[str, str]:
    """Persist settings update atomically.  Returns a status dict."""
    if "notification_webhook" in data.model_fields_set and data.notification_webhook:
        from app.utils.url_validation import is_safe_url

        if not await is_safe_url(data.notification_webhook):
            raise ValueError("Webhook URL points to a private/internal address")

    async with _SETTINGS_LOCK:
        fields_set = data.model_fields_set
        db_settings = _collect_general_db_settings(data, fields_set)

        await upsert_system_config_values(db, db_settings)
        await db.commit()
        await hydrate_runtime_settings_from_db(db, persist_normalized=True, commit=True)

        # Notify other replicas of config change via PostgreSQL LISTEN/NOTIFY
        from sqlalchemy import text

        await db.execute(text("SELECT pg_notify('config_changes', 'settings_updated')"))
        await db.commit()

    return {"status": "updated", "message": "Settings updated and saved"}


def get_current_settings() -> dict[str, Any]:
    """Return the full settings snapshot for the GET /api/settings endpoint."""
    return {
        **_build_settings_snapshot(_SETTINGS_SNAPSHOT_FIELDS_BEFORE_SANDBOX_STATUS),
        "sandbox_available": get_sandbox_status(),
        **_build_settings_snapshot(_SETTINGS_SNAPSHOT_FIELDS_AFTER_SANDBOX_STATUS),
    }


async def get_ai_status_snapshot() -> dict[str, Any]:
    """Build the AI status response payload."""
    from spectra_ai.llm import get_global_llm_client

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
    from spectra_ai.llm import get_global_llm_client

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
