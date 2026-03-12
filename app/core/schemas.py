"""Shared Pydantic schemas used across service and API layers.

These DTOs are consumed by both ``app.services`` and ``app.api``, so they
live in the ``core`` package to avoid a service → API import dependency.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# User DTOs (shared foundation — re-exported by app.api.schemas.auth)
# ---------------------------------------------------------------------------


class UserBase(BaseModel):
    """Base user schema with common fields."""

    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(
        ...,
        pattern=r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$",
        description="Valid email address",
    )


class UserCreate(UserBase):
    """Schema for user creation."""

    password: str = Field(..., min_length=8, description="Password (min 8 characters)")

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


# ---------------------------------------------------------------------------
# AI Provider helpers
# ---------------------------------------------------------------------------

_SUPPORTED_AI_PROVIDERS = {"ollama", "api", "openai", "litellm", "mock"}


def _normalize_ai_provider(value: str) -> str:
    provider = value.strip().lower()
    if provider not in _SUPPORTED_AI_PROVIDERS:
        raise ValueError("Unsupported provider")
    if provider != "mock":
        return "litellm"
    return provider


class AIProviderProfile(BaseModel):
    """Provider profile payload for runtime AI routing."""

    provider: str = Field(..., description="Provider id")
    model: str = Field(..., min_length=1, description="Model or provider/model route")
    base_url: str | None = None
    api_key: str | None = None

    @model_validator(mode="before")
    @classmethod
    def prefix_ollama_model(cls, data: Any) -> Any:
        """Add ollama/ prefix to model before provider gets normalized."""
        if isinstance(data, dict):
            raw_provider = str(data.get("provider", "")).strip().lower()
            model = str(data.get("model", "")).strip()
            if raw_provider == "ollama" and model and not model.startswith("ollama/"):
                data = {**data, "model": f"ollama/{model}"}
        return data

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        return _normalize_ai_provider(value)

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        model = value.strip()
        if not model:
            raise ValueError("Model is required")
        return model


class AIProviderRouting(BaseModel):
    """Default and per-tier route selection."""

    default: str | None = None
    tier1: str | None = None
    tier2: str | None = None
    tier3: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "default": self.default,
            "tier1": self.tier1,
            "tier2": self.tier2,
            "tier3": self.tier3,
        }


class AIProviderFallbacks(BaseModel):
    """Ordered fallback chain selection."""

    default: list[str] | None = None
    tier1: list[str] | None = None
    tier2: list[str] | None = None
    tier3: list[str] | None = None

    def as_dict(self) -> dict[str, list[str] | None]:
        return {
            "default": self.default,
            "tier1": self.tier1,
            "tier2": self.tier2,
            "tier3": self.tier3,
        }


# ---------------------------------------------------------------------------
# Setup & Settings DTOs
# ---------------------------------------------------------------------------


class SystemSetupRequest(BaseModel):
    """Schema for system setup."""

    user: UserCreate
    llm_provider: str | None = Field(None, pattern="^(ollama|api|litellm|mock)$")
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_api_base: str | None = None
    ollama_host: str | None = None
    ollama_model: str | None = None  # Ollama model when both providers configured
    provider_ollama: bool = False  # Whether ollama is enabled
    provider_api: bool = False  # Whether API is enabled
    provider_profiles: dict[str, AIProviderProfile] | None = None
    provider_routing: AIProviderRouting | None = None
    provider_fallbacks: AIProviderFallbacks | None = None
    # Per-tier model routing (optional)
    llm_tier1_model: str | None = None
    llm_tier2_model: str | None = None
    llm_tier3_model: str | None = None
    # Embedding configuration
    embedding_model: str | None = None
    # Infrastructure options
    use_custom_db: bool = False
    database_url: str | None = None
    # Service topology
    sandbox_orchestrator_url: str | None = None
    sandbox_orchestrator_api_key: str | None = None
    # Object Storage (S3/MinIO)
    s3_endpoint_url: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None

    @field_validator("llm_provider")
    @classmethod
    def normalize_llm_provider(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _normalize_ai_provider(value)

    @model_validator(mode="after")
    def validate_ai_config(self) -> SystemSetupRequest:
        if self.provider_profiles:
            return self
        if self.llm_provider and self.llm_model:
            return self
        raise ValueError("Either provider_profiles or llm_provider with llm_model is required")


class SettingsUpdateRequest(BaseModel):
    """Schema for settings updates with optional partial fields."""

    ai_provider: str | None = Field(None, pattern="^(ollama|api|litellm|mock)$")
    llm_api_key: str | None = None
    llm_api_base_url: str | None = None
    llm_model: str | None = None
    ollama_host: str | None = None
    ollama_model: str | None = None
    ollama_enabled: bool | None = None
    provider_profiles: dict[str, AIProviderProfile] | None = None
    provider_routing: AIProviderRouting | None = None
    provider_fallbacks: AIProviderFallbacks | None = None
    log_level: str | None = Field(None, pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    plugin_safe_mode: bool | None = None
    connect_back_host: str | None = None
    require_approval: bool | None = None
    fully_automated: bool | None = None
    notification_webhook: str | None = None
    llm_tier1_model: str | None = None
    llm_tier2_model: str | None = None
    llm_tier3_model: str | None = None
    embedding_model: str | None = None
    platform_domain: str | None = None
    platform_base_url: str | None = None
    platform_exposed: bool | None = None

    # Sandbox Pool
    sandbox_max_containers: int | None = Field(None, ge=1, le=50)
    sandbox_memory_limit: str | None = Field(None, pattern=r"^\d+[gGmM]$")
    sandbox_cpu_shares: int | None = Field(None, ge=128, le=4096)
    sandbox_max_lifetime: int | None = Field(None, ge=300, le=86400)

    # Sandbox Features
    sandbox_resource_tiers: str | None = None  # JSON string of tier definitions
    sandbox_network_isolation: bool | None = None
    sandbox_idle_timeout: int | None = Field(None, ge=60, le=7200)
    sandbox_heartbeat_interval: int | None = Field(None, ge=5, le=300)
    sandbox_per_user_limit: int | None = Field(None, ge=0, le=20)
    sandbox_default_priority: int | None = Field(None, ge=1, le=10)
    sandbox_oom_escalation_enabled: bool | None = None
    sandbox_warm_pool_enabled: bool | None = None
    sandbox_warm_pool_size: int | None = Field(None, ge=0, le=10)
    sandbox_auto_build_image: bool | None = None
    sandbox_image_scan_enabled: bool | None = None
    sandbox_image_scan_block_critical: bool | None = None

    # External Service Endpoints
    sandbox_orchestrator_url: str | None = None
    sandbox_orchestrator_timeout: int | None = Field(None, ge=5, le=300)

    # Object Storage (S3/MinIO)
    s3_endpoint_url: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_region: str | None = None

    @field_validator("sandbox_resource_tiers")
    @classmethod
    def validate_resource_tiers(cls, value: str | None) -> str | None:
        if value is not None and value != "":
            try:
                data = json.loads(value)
                if not isinstance(data, dict):
                    raise ValueError("Resource tiers must be a JSON object")
            except json.JSONDecodeError:
                raise ValueError("Resource tiers must be valid JSON")
        return value

    @field_validator("ai_provider")
    @classmethod
    def normalize_ai_provider(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _normalize_ai_provider(value)

    @field_validator("notification_webhook")
    @classmethod
    def validate_webhook_url(cls, value: str | None) -> str | None:
        if value is not None and value != "":
            from urllib.parse import urlparse

            parsed = urlparse(value)
            if parsed.scheme not in ("http", "https"):
                raise ValueError("Webhook URL must use http or https scheme")
        return value
