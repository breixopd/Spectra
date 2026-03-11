"""
Application configuration using Pydantic Settings.

Loads configuration from environment variables and .env files.
"""

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("spectra.core.config")


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- Application ---
    APP_NAME: str = "Spectra"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "text"  # "json" for structured logs in production, "text" for dev

    # --- Request Timeout ---
    REQUEST_TIMEOUT_SECONDS: int = 60  # Cancel requests exceeding this (0 = disabled)

    # --- Database (PostgreSQL) ---
    DATABASE_URL: SecretStr = SecretStr(
        "postgresql+asyncpg://spectra:spectra@db:5432/spectra"
    )
    DATABASE_ECHO: bool = False
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10

    # --- AI / LLM ---
    AI_PROVIDER: str = "litellm"  # litellm (all models), mock (testing only)
    OLLAMA_HOST: str = "http://ai:11434"
    OLLAMA_MODEL: str = "qwen2.5:3b"

    # Cloud/API Provider (OpenAI, OpenRouter, vLLM, LocalAI, etc.)
    LLM_API_KEY: SecretStr = SecretStr("")
    LLM_API_BASE_URL: str | None = None
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_TIMEOUT: float = 600.0

    # Per-tier model routing (empty = use default model for all tiers)
    LLM_TIER1_MODEL: str = ""  # Cheap/fast: scope, tool selection, parsing
    LLM_TIER2_MODEL: str = ""  # Balanced: planning, steering, reporting
    LLM_TIER3_MODEL: str = ""  # Capable: exploit crafting, PoC generation
    AI_PROVIDER_PROFILES: dict[str, dict[str, Any]] = Field(default_factory=dict)
    AI_PROVIDER_ROUTING: dict[str, str] = Field(default_factory=dict)
    AI_PROVIDER_FALLBACKS: dict[str, list[str]] = Field(default_factory=dict)

    # Embedding model (must be supported by LLM_API_BASE_URL provider)
    EMBEDDING_MODEL: str = "text-embedding-3-small"

    # --- Platform Settings ---
    PLATFORM_DOMAIN: str = ""  # Public domain (e.g., "spectra.example.com")
    PLATFORM_BASE_URL: str = ""  # Full base URL (e.g., "https://spectra.example.com")
    PLATFORM_EXPOSED: bool = False  # Whether platform is accessible from internet

    # --- Request Limits ---
    MAX_REQUEST_BODY_SIZE: int = 10 * 1024 * 1024  # 10 MB

    # --- CORS ---
    CORS_ORIGINS: list[str] = ["http://localhost:5000", "http://127.0.0.1:5000", "http://localhost:5050", "http://127.0.0.1:5050"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | list[str]) -> list[str] | str:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # --- JWT Authentication ---
    JWT_SECRET_KEY: SecretStr = SecretStr("")  # Must be set via env var or generated
    JWT_ALGORITHM: str = "HS256"
    # Security
    SECRET_KEY: SecretStr = SecretStr("change-me-in-production")  # Overridden by get_settings()
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 4  # 4 hours
    PLUGIN_SAFE_MODE: bool = True  # Enforce signature verification
    REQUIRE_APPROVAL: bool = False  # Require human approval for high-risk actions
    FULLY_AUTOMATED: bool = True  # Skip ALL human approval, fully autonomous operation
    CONNECT_BACK_HOST: str = "spectra-app"

    # --- Sandbox Pool ---
    SANDBOX_IMAGE: str = "spectra-tools"
    SANDBOX_NETWORK: str = "spectra-network"
    SANDBOX_MAX_CONTAINERS: int = 10
    SANDBOX_MEMORY_LIMIT: str = "2g"
    SANDBOX_CPU_SHARES: int = 512
    SANDBOX_RESOURCE_TIERS: str = '{"light": {"memory": "512m", "cpu_shares": 256}, "medium": {"memory": "2g", "cpu_shares": 512}, "heavy": {"memory": "4g", "cpu_shares": 1024}, "extreme": {"memory": "8g", "cpu_shares": 2048}}'
    SANDBOX_MAX_LIFETIME: int = 7200  # seconds
    SANDBOX_WORKER_POLL_DELAY: float = 0.5
    SANDBOX_NETWORK_ISOLATION: bool = True
    SANDBOX_IDLE_TIMEOUT: int = 600  # seconds — destroy sandbox if no heartbeat for this long
    SANDBOX_HEARTBEAT_INTERVAL: int = 30  # seconds — how often worker sends heartbeat
    SANDBOX_PER_USER_LIMIT: int = 3  # Max concurrent sandboxes per user
    SANDBOX_DEFAULT_PRIORITY: int = 5  # Default job priority (1=highest, 10=lowest)
    SANDBOX_OOM_ESCALATION_ENABLED: bool = True  # Auto-escalate resource tier on OOM (exit 137)
    SANDBOX_WARM_POOL_ENABLED: bool = False  # Disabled by default — pre-warms idle containers for instant assignment
    SANDBOX_WARM_POOL_SIZE: int = 2  # Number of pre-warmed idle containers to maintain
    SANDBOX_AUTO_BUILD_IMAGE: bool = True  # Auto-rebuild golden image when plugins change
    SANDBOX_IMAGE_SCAN_ENABLED: bool = True  # Scan golden image after each build for CVEs
    SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL: bool = False  # Block deployment if critical CVEs found

    # --- External Service Gateways ---
    # When set, the service uses an HTTP client to the external URL.
    # When empty/None, the service runs in-process (default monolith mode).

    # LLM gateway settings removed; use LLM_API_BASE_URL for OpenAI-compatible endpoints

    # Sandbox Orchestrator — external container management (for multi-node)
    SANDBOX_ORCHESTRATOR_URL: str | None = None  # e.g. "http://orchestrator:8084"
    SANDBOX_ORCHESTRATOR_TIMEOUT: int = 30
    SANDBOX_ORCHESTRATOR_API_KEY: SecretStr = SecretStr("")

    # VPN
    VPN_CONFIG_DIR: str = "/app/vpn_configs"
    VPN_ENABLED: bool = True
    VPN_AUTO_CONNECT: str = ""  # Reserved for future use

    # Notifications
    NOTIFICATION_WEBHOOK: str | None = None  # e.g., https://ntfy.sh/your-topic

    # --- Email / SMTP ---
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: SecretStr = SecretStr("")
    SMTP_FROM: str = ""
    SMTP_USE_TLS: bool = True

    # Multi-provider
    OLLAMA_ENABLED: bool = False  # Whether Ollama is available as secondary provider

    # --- Object Storage (S3/MinIO) ---
    S3_ENDPOINT_URL: str = ""  # MinIO/S3 endpoint (e.g., http://minio:9000)
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: SecretStr = SecretStr("")
    S3_REGION: str = "us-east-1"
    S3_BUCKET_MISSIONS: str = "spectra-missions"
    S3_BUCKET_SESSIONS: str = "spectra-sessions"
    S3_BUCKET_KNOWLEDGE: str = "spectra-knowledge"
    S3_BUCKET_BACKUPS: str = "spectra-backups"

    # --- Validators ---

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is a valid Python logging level."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid_levels:
            raise ValueError(f"LOG_LEVEL must be one of {valid_levels}")
        return v.upper()

    @field_validator("AI_PROVIDER")
    @classmethod
    def validate_ai_provider(cls, v: str) -> str:
        """Validate AI provider is supported."""
        valid_providers = {"ollama", "api", "litellm", "mock"}
        normalized = v.lower()
        if normalized not in valid_providers:
            raise ValueError(f"AI_PROVIDER must be one of {valid_providers}")
        if normalized == "api":
            return "litellm"
        return normalized

    @field_validator("ACCESS_TOKEN_EXPIRE_MINUTES")
    @classmethod
    def validate_token_expiry(cls, v: int) -> int:
        """Validate token expiry is reasonable."""
        if v < 5:
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES must be at least 5")
        if v > 1440 * 30:  # 30 days
            logger.warning("Token expiry is very long (%d minutes)", v)
        return v

    def save_runtime_settings(self):
        """Save current settings to a runtime JSON file for persistence.

        Runtime AI settings are intentionally excluded because SystemConfig is
        the authoritative source for provider, routing, fallback, and embedding
        configuration.
        """
        # We use the reports directory as it is mounted read-write
        settings_path = Path("data/config/runtime_settings.json")

        # Only save non-sensitive, non-AI compatibility settings.
        data = {
            "LOG_LEVEL": self.LOG_LEVEL,
            "PLUGIN_SAFE_MODE": self.PLUGIN_SAFE_MODE,
            "CONNECT_BACK_HOST": self.CONNECT_BACK_HOST,
            "REQUIRE_APPROVAL": self.REQUIRE_APPROVAL,
            "FULLY_AUTOMATED": self.FULLY_AUTOMATED,
            "NOTIFICATION_WEBHOOK": self.NOTIFICATION_WEBHOOK,
            "PLATFORM_DOMAIN": self.PLATFORM_DOMAIN,
            "PLATFORM_BASE_URL": self.PLATFORM_BASE_URL,
            "PLATFORM_EXPOSED": self.PLATFORM_EXPOSED,
        }

        try:
            import tempfile
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(settings_path.parent), suffix=".tmp"
            )
            try:
                with open(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                Path(tmp_path).replace(settings_path)
            except BaseException:
                Path(tmp_path).unlink(missing_ok=True)
                raise
        except Exception as e:
            logger.error("Failed to save runtime settings: %s", e)

    def load_runtime_settings(self):
        """Load settings from runtime JSON file if it exists.

        Runtime AI settings are intentionally ignored here because SystemConfig
        is authoritative for those values.
        """
        settings_path = Path("data/config/runtime_settings.json")
        if not settings_path.exists():
            return

        try:
            with open(settings_path, encoding="utf-8") as f:
                data = json.load(f)

            # Update fields if they exist in the file
            # Sensitive fields and DB-backed runtime AI settings are explicitly excluded.
            sensitive_fields = {
                "LLM_API_KEY",
                "JWT_SECRET_KEY",
                "DATABASE_URL",
            }
            db_backed_runtime_fields = {
                "AI_PROVIDER",
                "AI_PROVIDER_PROFILES",
                "AI_PROVIDER_ROUTING",
                "AI_PROVIDER_FALLBACKS",
                "OLLAMA_HOST",
                "OLLAMA_MODEL",
                "OLLAMA_ENABLED",
                "LLM_API_BASE_URL",
                "LLM_MODEL",
                "LLM_TIER1_MODEL",
                "LLM_TIER2_MODEL",
                "LLM_TIER3_MODEL",
                "EMBEDDING_MODEL",
            }
            for key, value in data.items():
                if (
                    hasattr(self, key)
                    and key not in sensitive_fields
                    and key not in db_backed_runtime_fields
                ):
                    setattr(self, key, value)
        except json.JSONDecodeError as e:
            logger.warning(
                "Runtime settings file is corrupted, renaming to .bak: %s", e
            )
            try:
                settings_path.rename(settings_path.with_suffix(".bak"))
            except OSError as rename_err:
                logger.error("Failed to rename corrupted settings file: %s", rename_err)
        except Exception as e:
            logger.error("Failed to load runtime settings: %s", e)


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    settings_instance = Settings()

    # Load runtime settings (overrides env vars for non-sensitive fields)
    settings_instance.load_runtime_settings()

    # Generate random secret key if not set
    if not settings_instance.JWT_SECRET_KEY.get_secret_value():
        if not settings_instance.DEBUG:
            logger.warning(
                "JWT_SECRET_KEY not set in production. Generating random key (sessions will invalid on restart)."
            )

        import secrets

        settings_instance.JWT_SECRET_KEY = SecretStr(secrets.token_urlsafe(32))

    # Auto-generate SECRET_KEY if empty or default
    if not settings_instance.SECRET_KEY or settings_instance.SECRET_KEY == "change-me-in-production":
        if not settings_instance.DEBUG:
            logger.warning(
                "SECRET_KEY not set or using default in production. Generating random key (sessions will invalidate on restart)."
            )

        import secrets

        settings_instance.SECRET_KEY = SecretStr(secrets.token_urlsafe(32))

    return settings_instance


# Singleton instance for direct import
settings = get_settings()
