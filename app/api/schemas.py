"""
Pydantic schemas for API requests and responses.

Provides input validation and serialization for all API endpoints.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.target import TargetStatus
from app.services.tools.models import ToolCategory, ToolStatus

# --- Auth Schemas ---


class Token(BaseModel):
    """JWT token response."""

    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Decoded JWT token data."""

    username: str | None = None


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
        """Validate password has minimum security requirements.

        Requirements:
        - At least 8 characters
        - At least one uppercase letter
        - At least one lowercase letter
        - At least one digit
        """
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class UserResponse(UserBase):
    """Schema for user response."""

    id: str
    is_active: bool
    is_superuser: bool

    model_config = ConfigDict(from_attributes=True)


# --- Target Schemas ---


class TargetCreate(BaseModel):
    """Schema for creating a new target."""

    address: str = Field(
        ...,
        min_length=3,
        max_length=255,
        description="IP address, CIDR, domain, or URL",
    )
    description: str | None = Field(None, max_length=1000)
    os: str | None = Field(None, max_length=100)
    status: TargetStatus = TargetStatus.PENDING

    @field_validator("address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        """Validate and normalize address."""
        if not v or not v.strip():
            raise ValueError("Address cannot be empty")
        return v.strip()


class TargetResponse(BaseModel):
    """Schema for target response."""

    id: str
    address: str
    description: str | None
    status: TargetStatus
    os: str | None
    created_at: str

    model_config = ConfigDict(from_attributes=True)


class TargetUpdate(BaseModel):
    """Schema for updating a target."""

    description: str | None = Field(None, max_length=1000)
    status: TargetStatus | None = None
    os: str | None = Field(None, max_length=100)


class FindingResponse(BaseModel):
    """Schema for finding response."""

    id: str
    title: str
    description: str | None
    severity: str
    status: str
    tool_source: str
    created_at: str

    model_config = ConfigDict(from_attributes=True)


# --- Mission Schemas ---


class StartMissionRequest(BaseModel):
    """Schema for starting a new mission."""

    target: str = Field(
        ..., min_length=1, max_length=500, description="Target IP, domain, or URL"
    )
    directive: str = Field(
        default="Perform a comprehensive security assessment",
        min_length=1,
        max_length=2000,
        description="High-level assessment directive (max 2000 chars)",
    )
    requirements: str | None = Field(
        default=None,
        max_length=5000,
        description="Optional scope, requirements, or constraints for the mission",
    )
    record_demo: bool = Field(
        default=False,
        description="Record a video walkthrough of the exploit workflow if exploitation succeeds",
    )
    vpn_config: str | None = Field(
        default=None,
        max_length=64,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9\-]{0,63}$",
        description="VPN config name to use for this mission",
    )

    @field_validator("target")
    @classmethod
    def validate_target(cls, v: str) -> str:
        """Validate and normalize target."""
        if not v or not v.strip():
            raise ValueError("Target cannot be empty")
        # Strip any control characters
        cleaned = "".join(c for c in v.strip() if c.isprintable() or c in " \t")
        return cleaned

    @field_validator("directive")
    @classmethod
    def validate_directive(cls, v: str) -> str:
        """Validate and sanitize directive."""
        if not v or not v.strip():
            return "Perform a comprehensive security assessment"
        # Strip any control characters that could be used for prompt injection
        cleaned = "".join(c for c in v.strip() if c.isprintable() or c in " \t\n")
        return cleaned


class MissionResponse(BaseModel):
    """Schema for mission response."""

    id: str
    target: str
    status: str
    current_phase: str | None = None
    logs: list[str]
    directive: str | None = None
    findings: list[dict] | None = None
    findings_count: int | None = None
    tools_run: list[str] = Field(default_factory=list)
    tool_executions: list[dict] | None = None
    report_path: str | None = None
    attack_surface: dict | None = None

    model_config = ConfigDict(from_attributes=True)


class MissionDetailResponse(MissionResponse):
    """Detailed mission response with summary."""

    directive: str | None = None
    summary: dict | None = None
    created_at: str


# --- Tool Schemas ---


class ToolSummary(BaseModel):
    """Summary of a registered tool."""

    id: str
    name: str
    version: str
    category: ToolCategory
    description: str
    status: ToolStatus
    icon: str
    color: str


class ToolListResponse(BaseModel):
    """Response for listing tools."""

    tools: list[ToolSummary]
    total: int


class ToolDetailResponse(BaseModel):
    """Detailed information about a tool."""

    id: str
    name: str
    version: str
    category: ToolCategory
    description: str
    status: ToolStatus
    installed_version: str | None
    error_message: str | None
    execution_command: str
    args_template: str
    timeout: int
    icon: str
    color: str


class PluginUploadResponse(BaseModel):
    """Response after uploading a plugin."""

    success: bool
    tool_id: str
    message: str


class InstallToolRequest(BaseModel):
    """Request to install a tool."""

    tool_id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


class InstallToolResponse(BaseModel):
    """Response after initiating tool installation."""

    success: bool
    tool_id: str
    status: str
    message: str


# --- Health Schemas ---


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    service: str
    error: str | None = None


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


class SystemSetupRequest(BaseModel):
    """Schema for system setup."""

    user: UserCreate
    llm_provider: str | None = Field(None, pattern="^(ollama|api|litellm|mock)$")
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


class PaginatedResponse(BaseModel):
    """Generic paginated list response."""

    items: list[Any]
    total: int
    page: int
    per_page: int
    pages: int = 0

    def __init__(self, **data: Any) -> None:
        if "pages" not in data and data.get("per_page"):
            data["pages"] = max(1, -(-data["total"] // data["per_page"]))  # ceil division
        super().__init__(**data)


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
