"""DB-backed runtime settings hydration and persistence."""

from __future__ import annotations

import inspect
import logging
import os

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_maker
from app.models.config import SystemConfig

logger = logging.getLogger(__name__)

BOOTSTRAP_ONLY_VARS: frozenset[str] = frozenset({
    "DATABASE_URL",
    "SERVICE_MODE",
    "LOG_LEVEL",
    "LOG_FORMAT",
    "DEBUG",
    "RATE_LIMIT_STORAGE",
    "DOCKER_REGISTRY",
    # Secrets managed separately by secret_bootstrap
    "JWT_SECRET_KEY",
    "SECRET_KEY",
    "SERVICE_AUTH_SECRET",
    "ENCRYPTION_KEY",
})


def _is_explicitly_set_env(key: str) -> bool:
    """Return True only if key exists in the actual OS environment."""
    return key in os.environ

_FERNET_TOKEN_PREFIX = "gAAAAA"


def _encrypt_config_value(value: str) -> str:
    """Encrypt a secret config value using the app encryption key."""
    if not value or value.startswith(_FERNET_TOKEN_PREFIX):
        return value
    try:
        from app.auth.encryption import _get_default_secret, encrypt_field

        return encrypt_field(value, _get_default_secret())
    except Exception:
        logger.debug("Value encryption failed", exc_info=True)
        return value


def _decrypt_config_value(value: str) -> str:
    """Decrypt a secret config value; return raw value if decryption fails."""
    if not value:
        return value
    try:
        from app.auth.encryption import _get_default_secret, decrypt_field

        return decrypt_field(value, _get_default_secret())
    except Exception:
        logger.debug("Value decryption failed", exc_info=True)
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
    "CONNECT_BACK_HOST": ("CONNECT_BACK_HOST", "str"),
    "REQUIRE_APPROVAL": ("REQUIRE_APPROVAL", "bool"),
    "NOTIFICATION_WEBHOOK": ("NOTIFICATION_WEBHOOK", "nullable_str"),
    "EMBEDDING_MODEL": ("EMBEDDING_MODEL", "str"),
    "EMBEDDING_API_KEY": ("EMBEDDING_API_KEY", "secret"),
    "EMBEDDING_API_BASE_URL": ("EMBEDDING_API_BASE_URL", "str"),
    "PLATFORM_DOMAIN": ("PLATFORM_DOMAIN", "str"),
    "PLATFORM_BASE_URL": ("PLATFORM_BASE_URL", "str"),
    "PLATFORM_EXPOSED": ("PLATFORM_EXPOSED", "bool"),
    # OTEL (DB-managed)
    "OTEL_EXPORTER_ENDPOINT": ("OTEL_EXPORTER_ENDPOINT", "str"),
    "OTEL_EXPORTER_PROTOCOL": ("OTEL_EXPORTER_PROTOCOL", "str"),
    "OTEL_SERVICE_NAME": ("OTEL_SERVICE_NAME", "str"),
    "OTEL_EXPORT_INTERVAL_SECONDS": ("OTEL_EXPORT_INTERVAL_SECONDS", "int"),
    # Database tuning (DB-managed)
    "DATABASE_ECHO": ("DATABASE_ECHO", "bool"),
    "DATABASE_POOL_SIZE": ("DATABASE_POOL_SIZE", "int"),
    "DATABASE_MAX_OVERFLOW": ("DATABASE_MAX_OVERFLOW", "int"),
    # Sandbox runtime limits/policies (DB-managed). Image/network/volume names
    # stay deployment-owned env/config so admins do not mutate platform plumbing.
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
    "SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL": ("SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL", "bool"),
    # External Service Endpoints
    "SANDBOX_ORCHESTRATOR_URL": ("SANDBOX_ORCHESTRATOR_URL", "nullable_str"),
    "SANDBOX_ORCHESTRATOR_TIMEOUT": ("SANDBOX_ORCHESTRATOR_TIMEOUT", "int"),
    # Shell Routing
    "SHELL_ROUTING_MODE": ("SHELL_ROUTING_MODE", "str"),
    "SHELL_LISTEN_HOST": ("SHELL_LISTEN_HOST", "str"),
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
    # Application
    "APP_NAME": ("APP_NAME", "str"),
    "JWT_ALGORITHM": ("JWT_ALGORITHM", "str"),
    "CORS_ORIGINS": ("CORS_ORIGINS", "csv_list"),
    "DOCKER_REGISTRY": ("DOCKER_REGISTRY", "str"),
    "MAX_REQUEST_BODY_SIZE": ("MAX_REQUEST_BODY_SIZE", "int"),
    "MAX_UPLOAD_SIZE": ("MAX_UPLOAD_SIZE", "int"),
    # VPN
    "VPN_ENABLED": ("VPN_ENABLED", "bool"),
    "VPN_CONFIG_DIR": ("VPN_CONFIG_DIR", "str"),
    "VPN_AUTO_CONNECT": ("VPN_AUTO_CONNECT", "str"),
    # MCP
    "MCP_API_KEY": ("MCP_API_KEY", "secret"),
    # Service URLs
    "AI_SERVICE_URL": ("AI_SERVICE_URL", "str"),
    "SCHEDULER_SERVICE_URL": ("SCHEDULER_SERVICE_URL", "str"),
    "WORKER_SERVICE_URL": ("WORKER_SERVICE_URL", "str"),
    # Garage
    "GARAGE_ADMIN_TOKEN": ("GARAGE_ADMIN_TOKEN", "secret"),
    "GARAGE_ADMIN_URL": ("GARAGE_ADMIN_URL", "str"),
    # S3 Buckets
    "S3_BUCKET_MISSIONS": ("S3_BUCKET_MISSIONS", "str"),
    "S3_BUCKET_SESSIONS": ("S3_BUCKET_SESSIONS", "str"),
    "S3_BUCKET_KNOWLEDGE": ("S3_BUCKET_KNOWLEDGE", "str"),
    "S3_BUCKET_VPN": ("S3_BUCKET_VPN", "str"),
    # Sandbox Orchestrator
    "SANDBOX_ORCHESTRATOR_API_KEY": ("SANDBOX_ORCHESTRATOR_API_KEY", "secret"),
    # Shell
    "SHELL_PROXY_NODES": ("SHELL_PROXY_NODES", "csv_list"),
    # Auto-healing
    "AUTO_HEAL_ENABLED": ("AUTO_HEAL_ENABLED", "bool"),
    "AUTO_HEAL_MAX_RETRIES": ("AUTO_HEAL_MAX_RETRIES", "int"),
    "AUTO_HEAL_COOLDOWN_SECS": ("AUTO_HEAL_COOLDOWN_SECS", "int"),
    # System thresholds
    "SYSTEM_MEMORY_ALERT_THRESHOLD": ("SYSTEM_MEMORY_ALERT_THRESHOLD", "int"),
    "SYSTEM_DISK_ALERT_THRESHOLD": ("SYSTEM_DISK_ALERT_THRESHOLD", "int"),
    "SYSTEM_LOAD_ALERT_MULTIPLIER": ("SYSTEM_LOAD_ALERT_MULTIPLIER", "float"),
    # Image
    "IMAGE_AUTO_UPDATE": ("IMAGE_AUTO_UPDATE", "bool"),
    "IMAGE_CHECK_INTERVAL": ("IMAGE_CHECK_INTERVAL", "int"),
    # Swarm service names
    "SWARM_WORKER_SERVICE": ("SWARM_WORKER_SERVICE", "str"),
    "SWARM_API_SERVICE": ("SWARM_API_SERVICE", "str"),
    "SWARM_AI_SERVICE": ("SWARM_AI_SERVICE", "str"),
    "SWARM_SCHEDULER_SERVICE": ("SWARM_SCHEDULER_SERVICE", "str"),
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


def _coerce_field_value(kind: str, value: str, key: str):
    """Coerce a raw string value to the appropriate Python type."""
    if kind == "bool":
        return _as_bool(value)
    if kind == "int":
        try:
            return int(value)
        except (ValueError, TypeError):
            logger.debug("Failed to parse int setting %s", key, exc_info=True)
            return None
    if kind == "float":
        try:
            return float(value)
        except (ValueError, TypeError):
            logger.debug("Failed to parse float setting %s", key, exc_info=True)
            return None
    if kind == "nullable_str":
        return value or None
    if kind == "secret":
        return SecretStr(value or "")
    if kind == "csv_list":
        return [i.strip() for i in value.split(",") if i.strip()] if value else []
    # default: str
    return value


def _apply_general_runtime_settings(rows: dict[str, str]) -> None:
    for key, (attr_name, kind) in GENERAL_RUNTIME_FIELD_MAP.items():
        if key not in rows:
            continue
        coerced = _coerce_field_value(kind, rows[key], key)
        if coerced is not None or kind == "nullable_str":
            setattr(settings, attr_name, coerced)


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

    # Env-var overrides: explicit env vars take precedence over DB values
    env_override_count = 0
    for key, (attr_name, kind) in GENERAL_RUNTIME_FIELD_MAP.items():
        if key in BOOTSTRAP_ONLY_VARS:
            continue
        if _is_explicitly_set_env(key):
            coerced = _coerce_field_value(kind, os.environ[key], key)
            if coerced is not None or kind == "nullable_str":
                setattr(settings, attr_name, coerced)
                env_override_count += 1

    if commit:
        await session.commit()

    if reset_caches:
        await reset_runtime_ai_caches()

    logger.info(
        "Runtime settings hydrated from DB (%d keys, %d env overrides)",
        len(row_map),
        env_override_count,
    )
