"""DB-backed runtime settings hydration and persistence.

AI config building / normalization lives in ``runtime_ai_config``.
This module re-exports the public symbols for backward compatibility.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_maker
from app.models.config import SystemConfig

# Re-export public API from the extracted module so that all existing
# ``from app.services.system.runtime_settings import X`` statements
# continue to work without modification.
from app.services.system.runtime_ai_config import (  # noqa: F401
    RuntimeAIConfig,
    _as_bool,
    _serialize_tier_model,
    build_runtime_ai_config_from_payload,
    get_resolved_runtime_ai_config_snapshot,
    get_runtime_ai_config_from_settings,
    normalize_runtime_ai_config,
    runtime_ai_rows_from_settings,
    serialize_runtime_ai_config_values,
)

logger = logging.getLogger(__name__)

NEW_AI_CONFIG_KEYS = (
    "AI_PROVIDER_PROFILES",
    "AI_PROVIDER_ROUTING",
    "AI_PROVIDER_FALLBACKS",
)
LEGACY_AI_CONFIG_KEYS = (
    "AI_PROVIDER",
    "LLM_MODEL",
    "LLM_TIER1_MODEL",
    "LLM_TIER2_MODEL",
    "LLM_TIER3_MODEL",
    "OLLAMA_ENABLED",
    "LLM_API_BASE_URL",
    "OLLAMA_HOST",
    "OLLAMA_MODEL",
    "LLM_API_KEY",
)
GENERAL_RUNTIME_FIELD_MAP: dict[str, tuple[str, str]] = {
    # S3/MinIO Object Storage
    "S3_ENDPOINT_URL": ("S3_ENDPOINT_URL", "str"),
    "S3_ACCESS_KEY": ("S3_ACCESS_KEY", "secret"),
    "S3_SECRET_KEY": ("S3_SECRET_KEY", "secret"),
    "S3_REGION": ("S3_REGION", "str"),
    "LOG_LEVEL": ("LOG_LEVEL", "str"),
    "PLUGIN_SAFE_MODE": ("PLUGIN_SAFE_MODE", "bool"),
    "CONNECT_BACK_HOST": ("CONNECT_BACK_HOST", "str"),
    "REQUIRE_APPROVAL": ("REQUIRE_APPROVAL", "bool"),
    "FULLY_AUTOMATED": ("FULLY_AUTOMATED", "bool"),
    "NOTIFICATION_WEBHOOK": ("NOTIFICATION_WEBHOOK", "nullable_str"),
    "EMBEDDING_MODEL": ("EMBEDDING_MODEL", "str"),
    "EMBEDDING_API_KEY": ("EMBEDDING_API_KEY", "secret"),
    "EMBEDDING_API_BASE_URL": ("EMBEDDING_API_BASE_URL", "str"),
    "PLATFORM_DOMAIN": ("PLATFORM_DOMAIN", "str"),
    "PLATFORM_BASE_URL": ("PLATFORM_BASE_URL", "str"),
    "PLATFORM_EXPOSED": ("PLATFORM_EXPOSED", "bool"),
    "SANDBOX_MAX_CONTAINERS": ("SANDBOX_MAX_CONTAINERS", "int"),
    "SANDBOX_MEMORY_LIMIT": ("SANDBOX_MEMORY_LIMIT", "str"),
    "SANDBOX_CPU_SHARES": ("SANDBOX_CPU_SHARES", "int"),
    "SANDBOX_MAX_LIFETIME": ("SANDBOX_MAX_LIFETIME", "int"),
    "SANDBOX_RESOURCE_TIERS": ("SANDBOX_RESOURCE_TIERS", "str"),
    "SANDBOX_NETWORK_ISOLATION": ("SANDBOX_NETWORK_ISOLATION", "bool"),
    "SANDBOX_IDLE_TIMEOUT": ("SANDBOX_IDLE_TIMEOUT", "int"),
    "SANDBOX_HEARTBEAT_INTERVAL": ("SANDBOX_HEARTBEAT_INTERVAL", "int"),
    "SANDBOX_PER_USER_LIMIT": ("SANDBOX_PER_USER_LIMIT", "int"),
    "SANDBOX_DEFAULT_PRIORITY": ("SANDBOX_DEFAULT_PRIORITY", "int"),
    "SANDBOX_OOM_ESCALATION_ENABLED": ("SANDBOX_OOM_ESCALATION_ENABLED", "bool"),
    "SANDBOX_WARM_POOL_ENABLED": ("SANDBOX_WARM_POOL_ENABLED", "bool"),
    "SANDBOX_WARM_POOL_SIZE": ("SANDBOX_WARM_POOL_SIZE", "int"),
    "SANDBOX_AUTO_BUILD_IMAGE": ("SANDBOX_AUTO_BUILD_IMAGE", "bool"),
    "SANDBOX_IMAGE_SCAN_ENABLED": ("SANDBOX_IMAGE_SCAN_ENABLED", "bool"),
    "SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL": ("SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL", "bool"),
    # External Service Endpoints
    # LLM gateway fields removed
    "SANDBOX_ORCHESTRATOR_URL": ("SANDBOX_ORCHESTRATOR_URL", "nullable_str"),
    "SANDBOX_ORCHESTRATOR_TIMEOUT": ("SANDBOX_ORCHESTRATOR_TIMEOUT", "int"),
    # Shell Routing
    "SHELL_ROUTING_MODE": ("SHELL_ROUTING_MODE", "str"),
    # Billing / Stripe
    "PAYMENT_PROVIDER": ("PAYMENT_PROVIDER", "str"),
    "STRIPE_PUBLISHABLE_KEY": ("STRIPE_PUBLISHABLE_KEY", "str"),
    "STRIPE_SECRET_KEY": ("STRIPE_SECRET_KEY", "secret"),
    "STRIPE_WEBHOOK_SECRET": ("STRIPE_WEBHOOK_SECRET", "secret"),
    # Crypto Payments
    "CRYPTO_PAYMENT_URL": ("CRYPTO_PAYMENT_URL", "str"),
    "CRYPTO_PAYMENT_API_KEY": ("CRYPTO_PAYMENT_API_KEY", "secret"),
    # Backup
    "BACKUP_ENABLED": ("BACKUP_ENABLED", "bool"),
    "BACKUP_SCHEDULE_HOURS": ("BACKUP_SCHEDULE_HOURS", "int"),
    "BACKUP_RETENTION_COUNT": ("BACKUP_RETENTION_COUNT", "int"),
    "BACKUP_S3_BUCKET": ("BACKUP_S3_BUCKET", "str"),
    # Maintenance
    "MAINTENANCE_MODE": ("MAINTENANCE_MODE", "bool"),
    "MAINTENANCE_MESSAGE": ("MAINTENANCE_MESSAGE", "str"),
}



async def get_runtime_setting_value(key: str) -> str | int | bool | None:
    """Get a single runtime setting value from DB."""
    field_info = GENERAL_RUNTIME_FIELD_MAP.get(key)
    if not field_info:
        return getattr(settings, key, None)
    _, field_type = field_info
    try:
        async with async_session_maker() as session:
            result = await session.execute(
                select(SystemConfig.value).where(SystemConfig.key == key)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return getattr(settings, key, None)
            if field_type == "bool":
                return _as_bool(row)
            if field_type == "int":
                return int(row)
            return row
    except (SQLAlchemyError, OSError):
        return getattr(settings, key, None)


def _apply_general_runtime_settings(rows: dict[str, str]) -> None:
    for key, (attr_name, kind) in GENERAL_RUNTIME_FIELD_MAP.items():
        if key not in rows:
            continue
        value = rows[key]
        if kind == "bool":
            setattr(settings, attr_name, _as_bool(value))
        elif kind == "int":
            try:
                setattr(settings, attr_name, int(value))
            except (ValueError, TypeError):
                pass  # Keep default if DB value is invalid
        elif kind == "nullable_str":
            setattr(settings, attr_name, value or None)
        elif kind == "secret":
            setattr(settings, attr_name, SecretStr(value or ""))
        else:
            setattr(settings, attr_name, value)


def apply_runtime_settings(rows: dict[str, str], runtime_ai_config: RuntimeAIConfig) -> None:
    """Apply DB-backed runtime settings to the in-memory settings singleton."""
    _apply_general_runtime_settings(rows)

    settings.AI_PROVIDER_PROFILES = runtime_ai_config.profiles
    settings.AI_PROVIDER_ROUTING = runtime_ai_config.routing
    settings.AI_PROVIDER_FALLBACKS = runtime_ai_config.fallbacks

    default_profile_name = runtime_ai_config.routing.get("default", "default")
    default_profile = runtime_ai_config.profiles.get(default_profile_name, {})
    default_provider = default_profile.get("provider", "mock")
    settings.AI_PROVIDER = default_provider

    cloud_profile = None
    for p in runtime_ai_config.profiles.values():
        if p.get("provider") == "litellm" and not str(p.get("model", "")).startswith("ollama/"):
            cloud_profile = p
            break
    if cloud_profile:
        settings.LLM_MODEL = str(cloud_profile.get("model", settings.LLM_MODEL))
        settings.LLM_API_BASE_URL = cloud_profile.get("base_url")
        api_key = cloud_profile.get("api_key")
        if api_key:
            settings.LLM_API_KEY = SecretStr(str(api_key))
        else:
            settings.LLM_API_KEY = SecretStr("")
    else:
        settings.LLM_API_BASE_URL = None
        settings.LLM_API_KEY = SecretStr("")

    ollama_profile = None
    for p in runtime_ai_config.profiles.values():
        if str(p.get("model", "")).startswith("ollama/"):
            ollama_profile = p
            break
    if ollama_profile:
        ollama_model = str(ollama_profile.get("model", settings.OLLAMA_MODEL))
        if ollama_model.startswith("ollama/"):
            ollama_model = ollama_model[len("ollama/") :]
        settings.OLLAMA_MODEL = ollama_model
        if ollama_profile.get("base_url"):
            settings.OLLAMA_HOST = str(ollama_profile["base_url"])

    default_model = str(default_profile.get("model", ""))
    if default_provider == "litellm":
        if default_model.startswith("ollama/"):
            settings.OLLAMA_MODEL = default_model[len("ollama/") :]
            if default_profile.get("base_url"):
                settings.OLLAMA_HOST = str(default_profile["base_url"])
        else:
            settings.LLM_MODEL = default_model or settings.LLM_MODEL
            settings.LLM_API_BASE_URL = default_profile.get("base_url")
            api_key = default_profile.get("api_key")
            if api_key:
                settings.LLM_API_KEY = SecretStr(str(api_key))
            else:
                settings.LLM_API_KEY = SecretStr("")

    settings.OLLAMA_ENABLED = any(
        str(profile.get("model", "")).startswith("ollama/")
        for profile_name, profile in runtime_ai_config.profiles.items()
        if profile_name != default_profile_name
    )
    settings.LLM_TIER1_MODEL = _serialize_tier_model("tier1", runtime_ai_config.routing, runtime_ai_config.profiles)
    settings.LLM_TIER2_MODEL = _serialize_tier_model("tier2", runtime_ai_config.routing, runtime_ai_config.profiles)
    settings.LLM_TIER3_MODEL = _serialize_tier_model("tier3", runtime_ai_config.routing, runtime_ai_config.profiles)


async def upsert_system_config_values(
    session: AsyncSession,
    values: dict[str, tuple[str, bool]],
) -> None:
    for key, (value, is_secret) in values.items():
        result = await session.execute(select(SystemConfig).where(SystemConfig.key == key))
        existing = result.scalar_one_or_none()
        if existing:
            existing.value = value
            existing.is_secret = is_secret
        else:
            session.add(SystemConfig(key=key, value=value, is_secret=is_secret))


async def _persist_normalized_runtime_ai_config(
    session: AsyncSession,
    runtime_ai_config: RuntimeAIConfig,
) -> None:
    await upsert_system_config_values(
        session,
        {
            "AI_PROVIDER_PROFILES": (json.dumps(runtime_ai_config.profiles, sort_keys=True), False),
            "AI_PROVIDER_ROUTING": (json.dumps(runtime_ai_config.routing, sort_keys=True), False),
            "AI_PROVIDER_FALLBACKS": (json.dumps(runtime_ai_config.fallbacks, sort_keys=True), False),
        },
    )


async def reset_runtime_ai_caches(preload: bool = False) -> None:
    """Reset cached AI router and LLM singletons after runtime config changes."""
    from app.services.ai.embeddings import EmbeddingService
    from app.services.ai.llm import close_global_llm_client, get_global_llm_client
    from app.services.ai.router import close_smart_router

    await close_global_llm_client()
    await close_smart_router()

    # Reset the embedding service so it picks up new credentials
    try:
        svc = EmbeddingService()
        svc._api_ready = False
        svc._litellm_kwargs = {}
    except (ImportError, AttributeError) as exc:
        logger.debug("Embedding service reset skipped: %s", exc)

    if preload:
        await get_global_llm_client()


async def hydrate_runtime_settings_from_db(
    session: AsyncSession | None = None,
    *,
    persist_normalized: bool = True,
    commit: bool = False,
    reset_caches: bool = True,
) -> RuntimeAIConfig:
    """Load authoritative runtime settings from DB and apply them in-memory."""
    owns_session = session is None
    if owns_session:
        async with async_session_maker() as owned_session:
            return await hydrate_runtime_settings_from_db(
                owned_session,
                persist_normalized=persist_normalized,
                commit=commit,
                reset_caches=reset_caches,
            )

    assert session is not None
    result = await session.execute(select(SystemConfig))
    rows = result.scalars().all()
    row_map = {row.key: row.value or "" for row in rows}

    runtime_ai_config = normalize_runtime_ai_config(row_map)
    apply_runtime_settings(row_map, runtime_ai_config)

    if persist_normalized:
        await _persist_normalized_runtime_ai_config(session, runtime_ai_config)
        if commit:
            await session.commit()

    if reset_caches:
        await reset_runtime_ai_caches()

    logger.info(
        "Runtime settings hydrated from DB: default=%s profiles=%d",
        runtime_ai_config.routing.get("default", "default"),
        len(runtime_ai_config.profiles),
    )
    return runtime_ai_config
