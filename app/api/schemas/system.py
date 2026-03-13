"""System, admin, health, and configuration schemas."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.schemas.auth import UserCreate

# --- Account Deletion ---


class DeleteAccountRequest(BaseModel):
    """Schema for account deletion confirmation."""

    password: str = Field(..., min_length=1, description="Current password for confirmation")


# --- Health Schemas ---


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    service: str
    error: str | None = None


# --- AI Provider Schemas ---

_SUPPORTED_AI_PROVIDERS = {"ollama", "api", "openai", "litellm", "mock", "qwen", "z.ai", "anthropic", "groq"}


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


# --- Setup & Settings Schemas ---


class SystemSetupRequest(BaseModel):
    """Schema for system setup."""

    user: UserCreate
    llm_provider: str | None = Field(None, pattern="^(ollama|api|litellm|mock|qwen|z\\.ai|anthropic|groq|openai)$")
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_api_base: str | None = None
    ollama_host: str | None = None
    ollama_model: str | None = None  # Ollama model when both providers configured
    provider_ollama: bool = False     # Whether ollama is enabled
    provider_api: bool = False        # Whether API is enabled
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
    def validate_ai_config(self) -> "SystemSetupRequest":
        if self.provider_profiles:
            return self
        if self.llm_provider and self.llm_model:
            return self
        raise ValueError(
            "Either provider_profiles or llm_provider with llm_model is required"
        )


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
    embedding_api_key: str | None = None
    embedding_api_base_url: str | None = None
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

    # Shell Routing
    shell_routing_mode: str | None = Field(None, pattern="^(direct|sandbox|proxy)$")

    # Object Storage (S3/MinIO)
    s3_endpoint_url: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_region: str | None = None

    @field_validator("sandbox_resource_tiers")
    @classmethod
    def validate_resource_tiers(cls, value: str | None) -> str | None:
        if value is not None and value != "":
            import json
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


class LLMTestRequest(BaseModel):
    """Schema for testing LLM connection."""

    provider: str
    model: str
    api_key: str | None = None
    base_url: str | None = None
    ollama_host: str | None = None

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        return _normalize_ai_provider(value)


# --- Admin Schemas ---


class UserAdminResponse(BaseModel):
    """User details for the admin panel."""

    id: str
    username: str
    email: str
    role: str
    is_active: bool
    is_superuser: bool
    plan_id: str | None = None
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


class UserCreateRequest(BaseModel):
    """Admin creating a user."""

    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(
        ...,
        pattern=r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$",
    )
    password: str = Field(..., min_length=8)
    role: str = Field(default="operator", pattern="^(admin|operator|viewer)$")
    plan_id: str | None = None

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


class UserUpdateRequest(BaseModel):
    """Admin updating a user."""

    email: str | None = Field(
        None,
        pattern=r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$",
    )
    role: str | None = Field(None, pattern="^(admin|operator|viewer)$")
    is_active: bool | None = None
    plan_id: str | None = None


class PlanCreateRequest(BaseModel):
    """Create a subscription plan."""

    name: str = Field(..., min_length=1, max_length=100)
    display_name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    is_default: bool = False
    sort_order: int = 0
    max_concurrent_missions: int = Field(default=1, ge=1)
    max_missions_per_month: int | None = None
    max_targets: int | None = None
    max_api_requests_per_hour: int = Field(default=100, ge=1)
    max_api_requests_per_day: int = Field(default=1000, ge=1)
    sandbox_max_containers: int = Field(default=1, ge=1)
    max_storage_mb: int = Field(default=500, ge=1)
    sandbox_resource_tier: str = Field("medium", pattern=r"^(light|medium|heavy|extreme)$")
    features: dict | None = None


class PlanUpdateRequest(BaseModel):
    """Update a subscription plan."""

    display_name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    is_default: bool | None = None
    sort_order: int | None = None
    max_concurrent_missions: int | None = Field(None, ge=1)
    max_missions_per_month: int | None = None
    max_targets: int | None = None
    max_api_requests_per_hour: int | None = Field(None, ge=1)
    max_api_requests_per_day: int | None = Field(None, ge=1)
    sandbox_max_containers: int | None = Field(None, ge=1)
    max_storage_mb: int | None = Field(None, ge=1)
    sandbox_resource_tier: str | None = Field(None, pattern=r"^(light|medium|heavy|extreme)$")
    features: dict | None = None


class PlanResponse(BaseModel):
    """Plan details."""

    id: str
    name: str
    display_name: str
    description: str | None = None
    is_active: bool
    is_default: bool
    sort_order: int
    max_concurrent_missions: int
    max_missions_per_month: int | None = None
    max_targets: int | None = None
    max_api_requests_per_hour: int
    max_api_requests_per_day: int
    sandbox_max_containers: int
    max_storage_mb: int
    sandbox_resource_tier: str
    features: dict | None = None

    model_config = ConfigDict(from_attributes=True)


# --- Server Provisioning Schemas ---


class ServerVerifyRequest(BaseModel):
    """Request to test SSH connectivity to a remote server."""

    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(22, ge=1, le=65535)
    username: str = Field("root", min_length=1, max_length=100)
    password: str | None = None
    private_key: str | None = None


class ServerProvisionRequest(BaseModel):
    """Request to auto-provision a Spectra service on a remote server."""

    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(22, ge=1, le=65535)
    username: str = Field("root", min_length=1, max_length=100)
    password: str | None = None
    private_key: str | None = None
    service_type: str = Field(..., pattern=r"^sandbox_worker$")
    service_port: int = Field(8080, ge=1, le=65535)
    extra_env: dict[str, str] = Field(default_factory=dict)
