"""
Application configuration using Pydantic Settings.

Loads configuration from environment variables and .env files.
"""

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import SecretStr, field_validator
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
    REQUEST_TIMEOUT: int = 60

    # --- Database (PostgreSQL) ---
    DATABASE_URL: SecretStr = SecretStr(
        "postgresql+asyncpg://spectra:spectra@db:5432/spectra"
    )
    DATABASE_ECHO: bool = False
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10

    # --- Redis ---
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: SecretStr = SecretStr("changeme")
    REDIS_DB: int = 0

    @property
    def REDIS_URL(self) -> str:
        """Construct Redis URL from components."""
        return f"redis://:{self.REDIS_PASSWORD.get_secret_value()}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # --- AI / LLM ---
    AI_PROVIDER: str = "ollama"  # ollama, api, mock
    OLLAMA_HOST: str = "http://ai:11434"
    OLLAMA_MODEL: str = "qwen2.5:3b"

    # Cloud/API Provider (OpenAI, OpenRouter, vLLM, LocalAI, etc.)
    LLM_API_KEY: SecretStr = SecretStr("")
    LLM_API_BASE_URL: str | None = None
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_TIMEOUT: float = 600.0

    # --- Plugin Security ---
    PLUGIN_SAFE_MODE: bool = True  # Enforce signature checks by default

    # --- CORS ---
    CORS_ORIGINS: List[str] = ["http://localhost:5000", "http://127.0.0.1:5000"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | List[str]) -> List[str] | str:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # --- JWT Authentication ---
    JWT_SECRET_KEY: SecretStr = SecretStr("")  # Must be set via env var or generated
    JWT_ALGORITHM: str = "HS256"
    # Security
    SECRET_KEY: str = "change-me-in-production"  # Fallback
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8  # 8 days
    PLUGIN_SAFE_MODE: bool = True  # Enforce signature verification
    REQUIRE_APPROVAL: bool = False  # Require human approval for high-risk actions
    FULLY_AUTOMATED: bool = True  # Skip ALL human approval, fully autonomous operation
    TOOL_CONTAINER_NAME: str = "spectra-tools"  # Default to standard container name
    CONNECT_BACK_HOST: str = "spectra-app"  # Host for reverse shells to connect back to

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
        valid_providers = {"ollama", "api", "mock"}
        if v.lower() not in valid_providers:
            raise ValueError(f"AI_PROVIDER must be one of {valid_providers}")
        return v.lower()

    @field_validator("ACCESS_TOKEN_EXPIRE_MINUTES")
    @classmethod
    def validate_token_expiry(cls, v: int) -> int:
        """Validate token expiry is reasonable."""
        if v < 5:
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES must be at least 5")
        if v > 1440 * 30:  # 30 days
            logger.warning("Token expiry is very long (%d minutes)", v)
        return v

    @field_validator("REDIS_PASSWORD")
    @classmethod
    def validate_redis_password(cls, v: str, info) -> str:
        """Warn if using default Redis password."""
        if v == "changeme":
            logger.warning(
                "Using default Redis password 'changeme'. This is insecure for production."
            )
        return v

    def save_runtime_settings(self):
        """Save current settings to a runtime JSON file for persistence.

        Note: Sensitive values (API keys) are NOT saved to this file.
        They should be stored in the database SystemConfig table with is_secret=True.
        """
        # We use the reports directory as it is mounted read-write
        settings_path = Path("reports/runtime_settings.json")

        # Only save non-sensitive configuration
        data = {
            "AI_PROVIDER": self.AI_PROVIDER,
            "OLLAMA_HOST": self.OLLAMA_HOST,
            "OLLAMA_MODEL": self.OLLAMA_MODEL,
            # Note: LLM_API_KEY is intentionally NOT saved here - use DB SystemConfig
            "LLM_API_BASE_URL": self.LLM_API_BASE_URL,
            "LLM_MODEL": self.LLM_MODEL,
            "LOG_LEVEL": self.LOG_LEVEL,
            "PLUGIN_SAFE_MODE": self.PLUGIN_SAFE_MODE,
            "CONNECT_BACK_HOST": self.CONNECT_BACK_HOST,
            "TOOL_CONTAINER_NAME": self.TOOL_CONTAINER_NAME,
            "REQUIRE_APPROVAL": self.REQUIRE_APPROVAL,
        }

        try:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            with open(settings_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Failed to save runtime settings: {e}")

    def load_runtime_settings(self):
        """Load settings from runtime JSON file if it exists.

        Note: LLM_API_KEY is loaded from DB SystemConfig, not from this file.
        """
        settings_path = Path("reports/runtime_settings.json")
        if not settings_path.exists():
            return

        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Update fields if they exist in the file
            # Sensitive fields are explicitly excluded
            sensitive_fields = {
                "LLM_API_KEY",
                "JWT_SECRET_KEY",
                "REDIS_PASSWORD",
                "DATABASE_URL",
            }
            for key, value in data.items():
                if hasattr(self, key) and key not in sensitive_fields:
                    setattr(self, key, value)
        except Exception as e:
            print(f"Failed to load runtime settings: {e}")


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

    return settings_instance


# Singleton instance for direct import
settings = get_settings()
