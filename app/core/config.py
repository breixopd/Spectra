"""
Application configuration using Pydantic Settings.

Loads configuration from environment variables and .env files.
"""

import logging
import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @model_validator(mode="before")
    @classmethod
    def load_file_secrets(cls, values: dict) -> dict:
        """Support Docker Swarm _FILE env vars that point to secret files."""
        file_mappings = {
            "JWT_SECRET_KEY_FILE": "JWT_SECRET_KEY",
            "DATABASE_URL_FILE": "DATABASE_URL",
            "SERVICE_AUTH_SECRET_FILE": "SERVICE_AUTH_SECRET",
        }
        for file_var, target_var in file_mappings.items():
            file_path = os.environ.get(file_var) or values.get(file_var)
            if file_path:
                secret_file = Path(file_path)
                if secret_file.is_file():
                    values[target_var] = secret_file.read_text().strip()
        return values

    # --- Application ---
    APP_NAME: str = "Spectra"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "text"  # "json" for structured logs in production, "text" for dev
    DATA_ROOT: str = "/app/data"

    # --- Request Timeout ---
    REQUEST_TIMEOUT_SECONDS: int = 60  # Cancel requests exceeding this (0 = disabled)

    @field_validator("REQUEST_TIMEOUT_SECONDS")
    @classmethod
    def validate_request_timeout(cls, v: int) -> int:
        if v != 0 and not 1 <= v <= 300:
            raise ValueError("REQUEST_TIMEOUT_SECONDS must be 0 (disabled) or 1-300")
        return v

    # --- Database (PostgreSQL) ---
    DATABASE_URL: SecretStr = SecretStr(
        "postgresql+asyncpg://spectra:spectra@db:5432/spectra"
    )
    DATABASE_ECHO: bool = False
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10

    @field_validator("DATABASE_POOL_SIZE")
    @classmethod
    def validate_pool_size(cls, v: int) -> int:
        if v < 1 or v > 100:
            raise ValueError("DATABASE_POOL_SIZE must be between 1 and 100")
        return v

    @field_validator("DATABASE_MAX_OVERFLOW")
    @classmethod
    def validate_max_overflow(cls, v: int) -> int:
        if v < 0 or v > 100:
            raise ValueError("DATABASE_MAX_OVERFLOW must be between 0 and 100")
        return v

    # --- AI / LLM (TensorZero Gateway) ---
    TENSORZERO_GATEWAY_URL: str = "http://tensorzero:3000"  # Auto-detected in Docker stack
    TENSORZERO_API_KEY: str = ""  # API key passed to TZ gateway (for provider auth)
    LLM_TIMEOUT: float = 600.0  # Request timeout for LLM calls

    @field_validator("LLM_TIMEOUT")
    @classmethod
    def validate_llm_timeout(cls, v: float) -> float:
        if not 5 <= v <= 1200:
            raise ValueError("LLM_TIMEOUT must be 5-1200 seconds")
        return v

    # Embedding model (local/ prefix uses fastembed; otherwise uses API)
    EMBEDDING_MODEL: str = "local/BAAI/bge-small-en-v1.5"
    EMBEDDING_API_KEY: SecretStr = Field(default=SecretStr(""), description="API key for embedding provider")
    EMBEDDING_API_BASE_URL: str = Field(default="", description="Base URL for embedding API")

    #: Whether to auto-initialize exploit database at startup (background task).
    EXPLOIT_DB_AUTO_INIT: bool = True

    # --- Platform Settings ---
    PLATFORM_DOMAIN: str = ""  # Public domain (e.g., "spectra.example.com")
    PLATFORM_BASE_URL: str = ""  # Full base URL (e.g., "https://spectra.example.com")
    PLATFORM_EXPOSED: bool = False  # Whether platform is accessible from internet

    # --- Maintenance ---
    MAINTENANCE_MODE: bool = False
    MAINTENANCE_MESSAGE: str = "We're performing scheduled maintenance. Please check back shortly."

    # --- Scheduler ---
    # Set False when running a dedicated scheduler service to prevent duplicate
    # maintenance tasks (sandbox watchdog, cache cleanup, periodic cleanup).
    SCHEDULER_ENABLED: bool = True

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
    ENCRYPTION_KEY: str = ""  # Separate key for data encryption (MFA secrets, BYOK credentials). Falls back to JWT_SECRET_KEY.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 4  # 4 hours
    PLUGIN_SAFE_MODE: bool = True  # Enforce signature verification
    REQUIRE_APPROVAL: bool = False  # Require human approval for high-risk actions
    # DEPRECATED: FULLY_AUTOMATED is now a per-mission setting (Mission.requires_approval).
    # Kept for backward compatibility with tests that monkeypatch it.
    # New missions use requires_approval=False (fully autonomous) by default.
    FULLY_AUTOMATED: bool = True  # Global fallback: skip ALL human approval

    # Rate limiting storage backend.
    # "memory://" for single-instance deployments (default).
    # For multi-instance, use "redis://host:6379" or Caddy's rate_limit module.
    RATE_LIMIT_STORAGE: str = "memory://"

    @field_validator("FULLY_AUTOMATED")
    @classmethod
    def warn_fully_automated(cls, v: bool) -> bool:
        import os
        if v and os.environ.get("ENVIRONMENT", "development") == "production":
            logging.getLogger(__name__).warning(
                "FULLY_AUTOMATED=true in production — human approval bypassed for all operations"
            )
        return v

    CONNECT_BACK_HOST: str = "spectra-app"

    # --- Sandbox Pool ---
    SANDBOX_IMAGE: str = "spectra-tools"
    SANDBOX_NETWORK: str = "spectra-network"
    SANDBOX_PLUGINS_VOLUME: str = "spectra_plugins"
    SANDBOX_MAX_CONTAINERS: int = 10

    @field_validator("SANDBOX_MAX_CONTAINERS")
    @classmethod
    def validate_sandbox_max_containers(cls, v: int) -> int:
        if not 1 <= v <= 100:
            raise ValueError("SANDBOX_MAX_CONTAINERS must be 1-100")
        return v
    SANDBOX_MEMORY_LIMIT: str = "2g"
    SANDBOX_CPU_SHARES: int = 512
    SANDBOX_RESOURCE_TIERS: str = '{"light": {"memory": "512m", "cpu_shares": 256}, "medium": {"memory": "2g", "cpu_shares": 512}, "heavy": {"memory": "4g", "cpu_shares": 1024}, "extreme": {"memory": "8g", "cpu_shares": 2048}}'
    SANDBOX_MAX_LIFETIME: int = 7200  # seconds

    @field_validator("SANDBOX_MAX_LIFETIME")
    @classmethod
    def validate_sandbox_lifetime(cls, v: int) -> int:
        if not 60 <= v <= 86400:
            raise ValueError("SANDBOX_MAX_LIFETIME must be 60-86400 seconds")
        return v
    SANDBOX_WORKER_POLL_DELAY: float = 0.5
    SANDBOX_NETWORK_ISOLATION: bool = True
    SANDBOX_IDLE_TIMEOUT: int = 600  # seconds — destroy sandbox if no heartbeat for this long
    SANDBOX_HEARTBEAT_INTERVAL: int = 30  # seconds — how often worker sends heartbeat
    SANDBOX_PER_USER_LIMIT: int = 3  # Max concurrent sandboxes per user

    @field_validator("SANDBOX_PER_USER_LIMIT")
    @classmethod
    def validate_sandbox_per_user(cls, v: int) -> int:
        if not 1 <= v <= 50:
            raise ValueError("SANDBOX_PER_USER_LIMIT must be 1-50")
        return v
    SANDBOX_DEFAULT_PRIORITY: int = 5  # Default job priority (1=highest, 10=lowest)
    SANDBOX_OOM_ESCALATION_ENABLED: bool = True  # Auto-escalate resource tier on OOM (exit 137)
    SANDBOX_WARM_POOL_ENABLED: bool = False  # Disabled by default — pre-warms idle containers for instant assignment
    SANDBOX_WARM_POOL_SIZE: int = 2  # Number of pre-warmed idle containers to maintain
    SANDBOX_AUTO_BUILD_IMAGE: bool = True  # Auto-rebuild golden image when plugins change
    SANDBOX_IMAGE_SCAN_ENABLED: bool = True  # Scan golden image after each build for CVEs
    SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL: bool = False  # Block deployment if critical CVEs found

    # --- Inter-Service Auth ---
    SERVICE_AUTH_SECRET: SecretStr = Field(default=SecretStr(""), description="Shared secret for inter-service authentication. Set same value on all services.")

    # --- Service Mode ---
    SERVICE_MODE: str = Field(default="monolith", description="Service mode: monolith, api, ai, scheduler, worker")

    # --- External Service Gateways ---
    # When set, the service uses an HTTP client to the external URL.
    # When empty/None, the service runs in-process (default monolith mode).

    # AI microservice — LLM, embeddings, RAG (for split mode)
    AI_SERVICE_URL: str = Field(default="", description="URL for AI microservice (empty = use in-process)")

    # Sandbox Orchestrator — external container management (for multi-node)
    SANDBOX_ORCHESTRATOR_URL: str | None = None  # e.g. "http://orchestrator:8084"
    SANDBOX_ORCHESTRATOR_TIMEOUT: int = 30
    SANDBOX_ORCHESTRATOR_API_KEY: SecretStr = SecretStr("")

    # --- Shell Routing ---
    SHELL_ROUTING_MODE: str = Field(default="direct", description="Shell routing: direct, sandbox, or proxy")
    SHELL_PROXY_NODES: list[str] = Field(default_factory=list, description="List of proxy node URLs for shell routing")

    @field_validator("SHELL_ROUTING_MODE")
    @classmethod
    def validate_shell_routing_mode(cls, v: str) -> str:
        allowed = {"direct", "sandbox", "proxy"}
        if v not in allowed:
            raise ValueError(f"SHELL_ROUTING_MODE must be one of {allowed}")
        return v

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
    EMAIL_VERIFICATION_ENABLED: bool = False  # Auto-enabled when SMTP is configured and verified

    @property
    def smtp_configured(self) -> bool:
        """Check if SMTP is configured with required fields."""
        return bool(self.SMTP_HOST and self.SMTP_USER)

    @field_validator("SMTP_PORT")
    @classmethod
    def validate_smtp_port(cls, v: int) -> int:
        if v < 1 or v > 65535:
            raise ValueError("SMTP_PORT must be between 1 and 65535")
        return v



    # --- Object Storage (S3/MinIO) ---
    # S3-compatible object storage (MinIO or AWS S3) is required.
    # Set S3_ENDPOINT_URL, S3_ACCESS_KEY, and S3_SECRET_KEY before starting.
    # Spectra will refuse to start without a working S3 configuration.
    S3_ENDPOINT_URL: str = ""  # MinIO/S3 endpoint (e.g., http://minio:9000)
    S3_ACCESS_KEY: SecretStr = SecretStr("")  # Required when S3_ENDPOINT_URL is set
    S3_SECRET_KEY: SecretStr = SecretStr("")  # Required when S3_ENDPOINT_URL is set
    S3_REGION: str = "us-east-1"
    S3_BUCKET_MISSIONS: str = "spectra-missions"
    S3_BUCKET_SESSIONS: str = "spectra-sessions"
    S3_BUCKET_KNOWLEDGE: str = "spectra-knowledge"
    # NOTE: Backup service is not yet implemented. These config keys are reserved
    # for a future automated backup feature. Do not remove — existing deployments may have these set.
    S3_BUCKET_BACKUPS: str = "spectra-backups"

    # --- Backup ---
    BACKUP_ENABLED: bool = Field(default=False, description="Enable automated backups")
    BACKUP_SCHEDULE_HOURS: int = Field(default=24, description="Backup interval in hours")
    BACKUP_RETENTION_COUNT: int = Field(default=10, description="Number of backups to retain")
    AUDIT_LOG_RETENTION_DAYS: int = Field(default=365, description="Days to retain audit log entries (0 = keep forever)")
    # NOTE: Backup service is not yet implemented. BACKUP_S3_BUCKET is a duplicate of S3_BUCKET_BACKUPS
    # and both are reserved for the future automated backup feature.
    BACKUP_S3_BUCKET: str = Field(default="spectra-backups", description="S3 bucket for backups")

    # --- Billing / Stripe ---
    PAYMENT_PROVIDER: str = Field(default="noop", description="Payment provider: noop, stripe, crypto, or manual")
    STRIPE_SECRET_KEY: SecretStr = Field(default=SecretStr(""), description="Stripe API secret key")
    STRIPE_WEBHOOK_SECRET: SecretStr = Field(default=SecretStr(""), description="Stripe webhook signing secret")
    STRIPE_PUBLISHABLE_KEY: str = Field(default="", description="Stripe publishable key for frontend")

    # --- Crypto Payments ---
    CRYPTO_PAYMENT_URL: str = Field(default="", description="Crypto payment provider URL (e.g., BTCPay Server)")
    CRYPTO_PAYMENT_API_KEY: SecretStr = Field(default=SecretStr(""), description="Crypto payment provider API key")

    # --- Validators ---

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is a valid Python logging level."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid_levels:
            raise ValueError(f"LOG_LEVEL must be one of {valid_levels}")
        return v.upper()

    @field_validator("ACCESS_TOKEN_EXPIRE_MINUTES")
    @classmethod
    def validate_token_expiry(cls, v: int) -> int:
        """Validate token expiry is reasonable."""
        if v < 5:
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES must be at least 5")
        if v > 1440 * 30:  # 30 days
            logger.warning("Token expiry is very long (%d minutes)", v)
        return v

    @field_validator("AUDIT_LOG_RETENTION_DAYS")
    @classmethod
    def validate_audit_retention(cls, v: int) -> int:
        if v < 0:
            raise ValueError("AUDIT_LOG_RETENTION_DAYS must be >= 0")
        return v


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    settings_instance = Settings()
    environment = os.environ.get("ENVIRONMENT", "development")

    # Auto-generate JWT secret if empty or using placeholder
    jwt_val = settings_instance.JWT_SECRET_KEY.get_secret_value()
    if not jwt_val or jwt_val.startswith("change-me"):
        if environment == "production":
            raise ValueError(
                "JWT_SECRET_KEY must be set in production. Refusing to boot with an empty or placeholder JWT secret."
            )
        if not settings_instance.DEBUG:
            logger.warning(
                "JWT_SECRET_KEY not set. Generating random key for non-production use (sessions will invalidate on restart)."
            )

        import secrets

        settings_instance.JWT_SECRET_KEY = SecretStr(secrets.token_urlsafe(32))

    # Auto-generate SECRET_KEY if empty or default
    secret_val = settings_instance.SECRET_KEY.get_secret_value()
    if not secret_val or secret_val == "change-me-in-production":
        if environment == "production":
            raise ValueError(
                "SECRET_KEY must be set in production. Refusing to boot with the insecure default or an empty secret."
            )
        if not settings_instance.DEBUG:
            logger.warning(
                "SECRET_KEY not set or using default. Generating random key for non-production use (sessions will invalidate on restart)."
            )

        import secrets

        settings_instance.SECRET_KEY = SecretStr(secrets.token_urlsafe(32))

    if (
        settings_instance.SERVICE_MODE != "monolith"
        and not settings_instance.SERVICE_AUTH_SECRET.get_secret_value()
    ):
        raise ValueError(
            "SERVICE_AUTH_SECRET must be set when SERVICE_MODE is not 'monolith'. "
            "Set a shared secret across all services."
        )

    return settings_instance


# Singleton instance for direct import
settings = get_settings()
