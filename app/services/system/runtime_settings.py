"""DB-backed runtime settings hydration and persistence."""

from __future__ import annotations

import inspect
import logging

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_maker
from app.models.config import SystemConfig

logger = logging.getLogger(__name__)

_FERNET_TOKEN_PREFIX = "gAAAAA"


def _encrypt_config_value(value: str) -> str:
    """Encrypt a secret config value using the app encryption key."""
    if not value or value.startswith(_FERNET_TOKEN_PREFIX):
        return value
    try:
        from app.core.encryption import _get_default_secret, encrypt_field

        return encrypt_field(value, _get_default_secret())
    except Exception:
        return value


def _decrypt_config_value(value: str) -> str:
    """Decrypt a secret config value; return raw value if decryption fails."""
    if not value:
        return value
    try:
        from app.core.encryption import _get_default_secret, decrypt_field

        return decrypt_field(value, _get_default_secret())
    except Exception:
        return value  # legacy unencrypted value — return as-is


def _as_bool(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


GENERAL_RUNTIME_FIELD_MAP: dict[str, tuple[str, str]] = {
    # AI Gateway
    "TENSORZERO_GATEWAY_URL": ("TENSORZERO_GATEWAY_URL", "str"),
    "TENSORZERO_API_KEY": ("TENSORZERO_API_KEY", "secret"),
    "LLM_TIMEOUT": ("LLM_TIMEOUT", "int"),
    # S3-compatible Object Storage
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
    "SANDBOX_WARM_POOL_SIZE": ("SANDBOX_WARM_POOL_SIZE", "int"),
    "SANDBOX_AUTO_BUILD_IMAGE": ("SANDBOX_AUTO_BUILD_IMAGE", "bool"),
    "SANDBOX_IMAGE_SCAN_ENABLED": ("SANDBOX_IMAGE_SCAN_ENABLED", "bool"),
    "SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL": ("SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL", "bool"),
    # External Service Endpoints
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
    "S3_BUCKET_BACKUPS": ("S3_BUCKET_BACKUPS", "str"),
    # Maintenance
    "MAINTENANCE_MODE": ("MAINTENANCE_MODE", "bool"),
    "MAINTENANCE_MESSAGE": ("MAINTENANCE_MESSAGE", "str"),
    # Auto-scaling
    "AUTOSCALE_ENABLED": ("AUTOSCALE_ENABLED", "bool"),
    "AUTOSCALE_WORKER_MIN": ("AUTOSCALE_WORKER_MIN", "int"),
    "AUTOSCALE_WORKER_MAX": ("AUTOSCALE_WORKER_MAX", "int"),
    "AUTOSCALE_API_MIN": ("AUTOSCALE_API_MIN", "int"),
    "AUTOSCALE_API_MAX": ("AUTOSCALE_API_MAX", "int"),
    "AUTOSCALE_AI_MAX": ("AUTOSCALE_AI_MAX", "int"),
    "AUTOSCALE_QUEUE_THRESHOLD": ("AUTOSCALE_QUEUE_THRESHOLD", "int"),
    "AUTOSCALE_COOLDOWN_SECS": ("AUTOSCALE_COOLDOWN_SECS", "int"),
    "AUTOSCALE_IDLE_SECS": ("AUTOSCALE_IDLE_SECS", "int"),
    "AUTOSCALE_CPU_UP_THRESHOLD": ("AUTOSCALE_CPU_UP_THRESHOLD", "int"),
    "AUTOSCALE_CPU_DOWN_THRESHOLD": ("AUTOSCALE_CPU_DOWN_THRESHOLD", "int"),
    # Infrastructure monitoring
    "INFRA_MONITOR_ENABLED": ("INFRA_MONITOR_ENABLED", "bool"),
    "INFRA_MONITOR_PG_THRESHOLD": ("INFRA_MONITOR_PG_THRESHOLD", "int"),
    "INFRA_MONITOR_REDIS_THRESHOLD": ("INFRA_MONITOR_REDIS_THRESHOLD", "int"),
    "INFRA_MONITOR_STORAGE_THRESHOLD": ("INFRA_MONITOR_STORAGE_THRESHOLD", "int"),
    # Session & Auth
    "ACCESS_TOKEN_EXPIRE_MINUTES": ("ACCESS_TOKEN_EXPIRE_MINUTES", "int"),
    "SESSION_IDLE_TIMEOUT_MINUTES": ("SESSION_IDLE_TIMEOUT_MINUTES", "int"),
    "ADMIN_IP_ALLOWLIST": ("ADMIN_IP_ALLOWLIST", "str"),
    "EMAIL_VERIFICATION_ENABLED": ("EMAIL_VERIFICATION_ENABLED", "bool"),
    # Maintenance
    "AUDIT_LOG_RETENTION_DAYS": ("AUDIT_LOG_RETENTION_DAYS", "int"),
    "MISSION_RETENTION_DAYS": ("MISSION_RETENTION_DAYS", "int"),
    "DB_MAINTENANCE_INTERVAL": ("DB_MAINTENANCE_INTERVAL", "int"),
    "STALE_JOB_RECOVERY_INTERVAL": ("STALE_JOB_RECOVERY_INTERVAL", "int"),
    "EXPLOIT_DB_REFRESH_HOURS": ("EXPLOIT_DB_REFRESH_HOURS", "int"),
    "DOCKER_CLEANUP_INTERVAL": ("DOCKER_CLEANUP_INTERVAL", "int"),
    "EXPLOIT_DB_AUTO_INIT": ("EXPLOIT_DB_AUTO_INIT", "bool"),
    # Email / SMTP
    "SMTP_HOST": ("SMTP_HOST", "str"),
    "SMTP_PORT": ("SMTP_PORT", "int"),
    "SMTP_USER": ("SMTP_USER", "str"),
    "SMTP_PASSWORD": ("SMTP_PASSWORD", "secret"),
    "SMTP_FROM": ("SMTP_FROM", "str"),
    "SMTP_USE_TLS": ("SMTP_USE_TLS", "bool"),
    # Request handling
    "REQUEST_TIMEOUT_SECONDS": ("REQUEST_TIMEOUT_SECONDS", "int"),
    "SANDBOX_WORKER_POLL_DELAY": ("SANDBOX_WORKER_POLL_DELAY", "str"),
}


async def get_runtime_setting_value(key: str) -> str | int | bool | None:
    """Get a single runtime setting value from DB."""
    field_info = GENERAL_RUNTIME_FIELD_MAP.get(key)
    if not field_info:
        return getattr(settings, key, None)
    _, field_type = field_info
    try:
        async with async_session_maker() as session:
            result = await session.execute(select(SystemConfig).where(SystemConfig.key == key))
            obj = result.scalar_one_or_none()
            if inspect.isawaitable(obj):
                obj = await obj
            if obj is None:
                return getattr(settings, key, None)
            row = _decrypt_config_value(obj.value or "") if getattr(obj, "is_secret", False) else (obj.value or "")
            if field_type == "bool":
                return _as_bool(row)
            if field_type == "int":
                return int(row)
            return row
    except (SQLAlchemyError, OSError):
        return getattr(settings, key, None)


async def get_runtime_setting_str(key: str, default: str = "") -> str:
    """Get a single runtime setting as a string."""
    val = await get_runtime_setting_value(key)
    return str(val) if val is not None else default


async def get_runtime_setting_int(key: str, default: int = 0) -> int:
    """Get a single runtime setting as an integer."""
    val = await get_runtime_setting_value(key)
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        try:
            return int(val)
        except ValueError:
            return default
    return default


async def get_runtime_setting_bool(key: str, default: bool = False) -> bool:
    """Get a single runtime setting as a boolean."""
    val = await get_runtime_setting_value(key)
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return default


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
                logger.debug("Failed to parse int setting %s", key, exc_info=True)
        elif kind == "nullable_str":
            setattr(settings, attr_name, value or None)
        elif kind == "secret":
            setattr(settings, attr_name, SecretStr(value or ""))
        else:
            setattr(settings, attr_name, value)


async def upsert_system_config_values(
    session: AsyncSession,
    values: dict[str, tuple[str, bool]],
) -> None:
    for key, (value, is_secret) in values.items():
        stored = _encrypt_config_value(value) if is_secret else value
        result = await session.execute(select(SystemConfig).where(SystemConfig.key == key))
        existing = result.scalar_one_or_none()
        if existing:
            existing.value = stored
            existing.is_secret = is_secret
        else:
            session.add(SystemConfig(key=key, value=stored, is_secret=is_secret))


async def reset_runtime_ai_caches(preload: bool = False) -> None:
    """Reset cached AI router and LLM singletons after runtime config changes."""
    from app.services.ai.embeddings import EmbeddingService
    from app.services.ai.llm import close_global_llm_client, get_global_llm_client
    from app.services.ai.router import close_smart_router

    await close_global_llm_client()
    await close_smart_router()

    try:
        svc = EmbeddingService()
        svc._api_ready = False
        svc._openai_client = None
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
) -> None:
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

    if session is None:
        raise RuntimeError("Session is required")
    result = await session.execute(select(SystemConfig))
    rows = result.scalars().all()
    row_map = {
        row.key: (_decrypt_config_value(row.value or "") if getattr(row, "is_secret", False) else (row.value or ""))
        for row in rows
    }

    _apply_general_runtime_settings(row_map)

    if commit:
        await session.commit()

    if reset_caches:
        await reset_runtime_ai_caches()

    logger.info("Runtime settings hydrated from DB (%d keys)", len(row_map))
