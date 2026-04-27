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
            "SECRET_KEY_FILE": "SECRET_KEY",
            "DATABASE_URL_FILE": "DATABASE_URL",
            "SERVICE_AUTH_SECRET_FILE": "SERVICE_AUTH_SECRET",
            "ENCRYPTION_KEY_FILE": "ENCRYPTION_KEY",
            "S3_ACCESS_KEY_FILE": "S3_ACCESS_KEY",
            "S3_SECRET_KEY_FILE": "S3_SECRET_KEY",
            "REDIS_PASSWORD_FILE": "REDIS_PASSWORD",
            "CLICKHOUSE_PASSWORD_FILE": "CLICKHOUSE_PASSWORD",
            "OPENAI_API_KEY_FILE": "OPENAI_API_KEY",
            "GARAGE_ADMIN_TOKEN_FILE": "GARAGE_ADMIN_TOKEN",
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
    APP_ENV: str = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "text"  # "json" for structured logs in production, "text" for dev

    # --- OpenTelemetry Export (DB-managed, defaults used before DB is available) ---
    OTEL_EXPORTER_ENDPOINT: str = ""  # e.g. "http://otel-collector:4318" — empty = disabled
    OTEL_EXPORTER_PROTOCOL: str = "http/protobuf"  # or "http/json"
    OTEL_SERVICE_NAME: str = "spectra"
    OTEL_EXPORT_INTERVAL_SECONDS: int = 30

    # --- Request Timeout ---
    REQUEST_TIMEOUT_SECONDS: int = 60  # Cancel requests exceeding this (0 = disabled)

    @field_validator("REQUEST_TIMEOUT_SECONDS")
    @classmethod
    def validate_request_timeout(cls, v: int) -> int:
        if v != 0 and not 1 <= v <= 300:
            raise ValueError("REQUEST_TIMEOUT_SECONDS must be 0 (disabled) or 1-300")
        return v

    # --- Database (PostgreSQL) ---
    # Primary persistent store, PostgreSQL-backed app cache, job queue, and
    # LISTEN/NOTIFY backbone.
    DATABASE_URL: SecretStr = SecretStr("")
    DATABASE_ECHO: bool = False
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10

    @model_validator(mode="after")
    def _adjust_pool_for_service(self):
        """Auto-tune pool size based on SERVICE_MODE when not explicitly overridden."""
        if self.DATABASE_POOL_SIZE == 20:  # Only if not explicitly overridden
            mode = self.SERVICE_MODE
            if mode == "scheduler":
                self.DATABASE_POOL_SIZE = 8
                self.DATABASE_MAX_OVERFLOW = 8
            elif mode == "worker":
                self.DATABASE_POOL_SIZE = 5
                self.DATABASE_MAX_OVERFLOW = 5
            elif mode == "ai":
                self.DATABASE_POOL_SIZE = 10
                self.DATABASE_MAX_OVERFLOW = 5
        return self

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
    LLM_TIMEOUT: float = 120.0  # Request timeout for LLM calls

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

    # --- Request Limits ---
    MAX_REQUEST_BODY_SIZE: int = 10 * 1024 * 1024  # 10 MB
    MAX_UPLOAD_SIZE: int = 50 * 1024 * 1024  # 50 MB — multipart file uploads

    # --- CORS ---
    CORS_ORIGINS: list[str] = [
        "http://localhost:5000",
        "http://127.0.0.1:5000",
        "http://localhost:5050",
        "http://127.0.0.1:5050",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | list[str]) -> list[str] | str:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    @field_validator("CORS_ORIGINS")
    @classmethod
    def validate_cors_origins(cls, v: list[str]) -> list[str]:
        if any(origin.strip() == "*" for origin in v):
            raise ValueError("CORS_ORIGINS cannot contain '*' entries")
        return v

    # --- JWT Authentication ---
    JWT_SECRET_KEY: SecretStr = SecretStr("")  # Must be set via env var or generated
    JWT_ALGORITHM: str = "HS256"
    # Security
    SECRET_KEY: SecretStr = SecretStr("")  # Must be set via env var; get_settings() validates
    ENCRYPTION_KEY: str = (
        ""  # Separate key for data encryption (MFA secrets, BYOK credentials). Falls back to JWT_SECRET_KEY.
    )
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 4  # 4 hours
    SESSION_IDLE_TIMEOUT_MINUTES: int = 60  # 0 = disabled
    REQUIRE_APPROVAL: bool = False  # Require human approval for high-risk actions

    # Rate limiting storage backend.
    # PostgreSQL remains the persistent state store, PostgreSQL-backed app
    # cache, job queue, and LISTEN/NOTIFY backbone; it does not share
    # rate-limit counters.
    # Deployment default is Redis so counters stay shared across app replicas.
    # Use "memory://" mainly for tests or intentionally ephemeral local runs.
    # Use Caddy's rate_limit module only if you intentionally want rate
    # limiting to live entirely at the reverse proxy edge.
    RATE_LIMIT_STORAGE: str = "redis://redis:6379/0"
    REDIS_PASSWORD: SecretStr = SecretStr("")
    REDIS_URL: str = Field(
        default="",
        description="Redis URL for general caching. Falls back to RATE_LIMIT_STORAGE if empty.",
    )

    CONNECT_BACK_HOST: str = "spectra-app"

    DOCKER_REGISTRY: str = "ghcr.io/spectra"

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
    SANDBOX_WARM_POOL_SIZE: int = 2  # Number of pre-warmed idle containers to maintain
    SANDBOX_AUTO_BUILD_IMAGE: bool = True  # Auto-rebuild golden image when plugins change
    SANDBOX_IMAGE_SCAN_ENABLED: bool = True  # Scan golden image after each build for CVEs
    SANDBOX_IMAGE_SCAN_BLOCK_CRITICAL: bool = False  # Block deployment if critical CVEs found
    TOOL_QUEUE_NAME: str = "default"  # Queue used for shared plugin/tool execution workers

    # --- Inter-Service Auth ---
    SERVICE_AUTH_SECRET: SecretStr = Field(
        default=SecretStr(""),
        description="Shared secret for inter-service authentication. Set same value on all services.",
    )

    # --- Service Mode ---
    SERVICE_MODE: str = Field(default="api", description="Service mode: api, ai, scheduler, worker")

    # --- MCP Server ---
    MCP_API_KEY: str = ""  # API key for MCP server access (leave empty to disable)
    MCP_USER_ID: str = ""  # User ID bound to the MCP API key (required for user-scoped operations)

    # --- External Service Gateways ---
    # URL to the AI microservice. Must be set for production.
    AI_SERVICE_URL: str = ""
    SCHEDULER_SERVICE_URL: str = "http://scheduler:5011"
    WORKER_SERVICE_URL: str = "http://worker:5012"

    # Sandbox Orchestrator — external container management (for multi-node)
    SANDBOX_ORCHESTRATOR_URL: str | None = None  # e.g. "http://orchestrator:8084"
    SANDBOX_ORCHESTRATOR_TIMEOUT: int = 30
    SANDBOX_ORCHESTRATOR_API_KEY: SecretStr = SecretStr("")

    # --- Shell Routing ---
    SHELL_ROUTING_MODE: str = Field(default="direct", description="Shell routing: direct, sandbox, or proxy")
    SHELL_LISTEN_HOST: str = Field(default="127.0.0.1", description="Host/interface for worker-side callback listeners")
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

    # --- Object Storage (S3-compatible storage: Garage or any S3 provider) ---
    # S3-compatible object storage (Garage, AWS S3, or any S3 provider) is required.
    # Set S3_ENDPOINT_URL, S3_ACCESS_KEY, and S3_SECRET_KEY before starting.
    # Spectra will refuse to start without a working S3 configuration.
    S3_ENDPOINT_URL: str = ""  # S3-compatible endpoint (e.g., http://garage:3900)
    S3_ACCESS_KEY: SecretStr = SecretStr("")  # Required when S3_ENDPOINT_URL is set
    S3_SECRET_KEY: SecretStr = SecretStr("")  # Required when S3_ENDPOINT_URL is set
    S3_REGION: str = "us-east-1"
    S3_BUCKET_MISSIONS: str = "spectra-missions"
    S3_BUCKET_SESSIONS: str = "spectra-sessions"
    S3_BUCKET_KNOWLEDGE: str = "spectra-knowledge"
    S3_BUCKET_VPN: str = "spectra-sessions"  # Reuse sessions bucket with vpn/ prefix
    # Used by BackupService (app/services/infrastructure/backup.py) for automated backups
    S3_BUCKET_BACKUPS: str = "spectra-backups"

    # Garage Admin API token for first-boot bootstrap (layout, keys, buckets).
    # Only needed when running Garage as the S3 backend. Empty = skip bootstrap.
    GARAGE_ADMIN_TOKEN: str = ""
    GARAGE_ADMIN_URL: str = ""  # e.g. http://garage:3903; auto-derived from S3_ENDPOINT_URL if empty

    # --- Backup ---
    BACKUP_ENABLED: bool = Field(default=False, description="Enable automated backups")
    BACKUP_SCHEDULE_HOURS: int = Field(default=24, description="Backup interval in hours")
    BACKUP_RETENTION_COUNT: int = Field(default=10, description="Number of backups to retain")
    AUDIT_LOG_RETENTION_DAYS: int = Field(
        default=365, description="Days to retain audit log entries (0 = keep forever)"
    )
    MISSION_RETENTION_DAYS: int = 0  # 0 = keep forever, >0 = auto-delete completed missions after N days
    ADMIN_IP_ALLOWLIST: str = ""  # Comma-separated list of allowed IPs/CIDRs for admin routes, empty = disabled

    # --- Auto-Scaling ---
    AUTOSCALE_ENABLED: bool = False  # Opt-in, safe default
    AUTOSCALE_WORKER_MIN: int = 1
    AUTOSCALE_WORKER_MAX: int = 10
    AUTOSCALE_API_MIN: int = 1
    AUTOSCALE_API_MAX: int = 5
    AUTOSCALE_AI_MAX: int = 3
    AUTOSCALE_QUEUE_THRESHOLD: int = 10  # Queue depth to trigger scale-up
    AUTOSCALE_COOLDOWN_SECS: int = 300  # 5 min between scale actions
    AUTOSCALE_IDLE_SECS: int = 300  # 5 min idle before scale-down
    AUTOSCALE_CPU_UP_THRESHOLD: int = 75  # CPU % to trigger scale-up
    AUTOSCALE_CPU_DOWN_THRESHOLD: int = 25  # CPU % to trigger scale-down

    # Service names (Docker Swarm or Compose)
    SWARM_WORKER_SERVICE: str = "spectra_worker"
    SWARM_API_SERVICE: str = "spectra_app"
    SWARM_AI_SERVICE: str = "spectra_ai-svc"
    SWARM_SCHEDULER_SERVICE: str = "spectra_scheduler"

    # Infrastructure monitoring
    INFRA_MONITOR_ENABLED: bool = True
    INFRA_MONITOR_PG_THRESHOLD: int = 80  # PostgreSQL connection % alert threshold
    INFRA_MONITOR_REDIS_THRESHOLD: int = 85  # Redis memory % alert threshold
    INFRA_MONITOR_STORAGE_THRESHOLD: int = 90  # Garage/S3 storage % alert threshold

    # Auto-healing
    AUTO_HEAL_ENABLED: bool = True
    AUTO_HEAL_MAX_RETRIES: int = 3
    AUTO_HEAL_COOLDOWN_SECS: int = 300

    # System resource thresholds
    SYSTEM_MEMORY_ALERT_THRESHOLD: int = 90  # percent
    SYSTEM_DISK_ALERT_THRESHOLD: int = 85  # percent
    SYSTEM_LOAD_ALERT_MULTIPLIER: float = 2.0  # x CPUs

    # --- Automated Maintenance ---
    DB_MAINTENANCE_INTERVAL: int = Field(default=604800, description="DB VACUUM ANALYZE interval in seconds (7 days)")
    STALE_JOB_RECOVERY_INTERVAL: int = Field(default=300, description="Stale job recovery interval in seconds")
    EXPLOIT_DB_REFRESH_HOURS: int = Field(default=168, description="Exploit DB refresh interval in hours (7 days)")
    DOCKER_CLEANUP_INTERVAL: int = Field(default=604800, description="Docker resource pruning interval in seconds (7 days)")

    # --- Image Auto-Update ---
    IMAGE_AUTO_UPDATE: bool = Field(default=False, description="Enable automatic registry polling and rollout when new image digests are found")
    IMAGE_CHECK_INTERVAL: int = Field(default=60, description="Seconds between automatic image update checks when enabled")

    @field_validator("IMAGE_CHECK_INTERVAL")
    @classmethod
    def validate_image_check_interval(cls, v: int) -> int:
        if not 10 <= v <= 3600:
            raise ValueError("IMAGE_CHECK_INTERVAL must be 10-3600 seconds")
        return v

    # --- Billing / Stripe ---
    PAYMENT_PROVIDER: str = Field(default="manual", description="Payment provider: manual, stripe, crypto, or noop")
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
    import secrets as _secrets

    settings_instance = Settings()
    production_like = settings_instance.APP_ENV.lower() in {"production", "prod"} and not settings_instance.DEBUG

    # Auto-generate JWT secret if empty or using placeholder
    jwt_val = settings_instance.JWT_SECRET_KEY.get_secret_value()
    if not jwt_val or jwt_val.startswith("change-me"):
        if production_like:
            raise ValueError("JWT_SECRET_KEY must be explicitly set in production")
        settings_instance.JWT_SECRET_KEY = SecretStr(_secrets.token_urlsafe(32))

    # Auto-generate SECRET_KEY if empty or default
    secret_val = settings_instance.SECRET_KEY.get_secret_value()
    if not secret_val or secret_val == "change-me-in-production":
        if production_like:
            raise ValueError("SECRET_KEY must be explicitly set in production")
        settings_instance.SECRET_KEY = SecretStr(_secrets.token_urlsafe(32))

    # Auto-generate SERVICE_AUTH_SECRET if empty
    if not settings_instance.SERVICE_AUTH_SECRET.get_secret_value():
        if production_like:
            raise ValueError("SERVICE_AUTH_SECRET must be explicitly set in production")
        settings_instance.SERVICE_AUTH_SECRET = SecretStr(_secrets.token_urlsafe(32))

    if settings_instance.RATE_LIMIT_STORAGE == "redis://redis:6379/0":
        redis_password = settings_instance.REDIS_PASSWORD.get_secret_value()
        if redis_password:
            settings_instance.RATE_LIMIT_STORAGE = f"redis://:{redis_password}@redis:6379/0"

    if not settings_instance.REDIS_URL:
        settings_instance.REDIS_URL = settings_instance.RATE_LIMIT_STORAGE

    # Auto-generate ENCRYPTION_KEY if empty
    if not settings_instance.ENCRYPTION_KEY:
        # Persist to filesystem so the key survives container restarts
        env_explicit = os.environ.get("ENCRYPTION_KEY")
        if not env_explicit:
            if production_like:
                raise ValueError("ENCRYPTION_KEY must be explicitly set in production")
            key_path = Path("/app/data") / ".encryption_key"
            try:
                if key_path.is_file():
                    settings_instance.ENCRYPTION_KEY = key_path.read_text().strip()
                else:
                    new_key = _secrets.token_urlsafe(32)
                    key_path.parent.mkdir(parents=True, exist_ok=True)
                    # Atomic write with restrictive permissions
                    tmp_path = key_path.with_suffix(".tmp")
                    fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    try:
                        os.write(fd, new_key.encode())
                    finally:
                        os.close(fd)
                    os.replace(str(tmp_path), str(key_path))
                    settings_instance.ENCRYPTION_KEY = new_key
            except OSError:
                settings_instance.ENCRYPTION_KEY = _secrets.token_urlsafe(32)
        else:
            settings_instance.ENCRYPTION_KEY = env_explicit

    return settings_instance


# Singleton instance for direct import
settings = get_settings()
