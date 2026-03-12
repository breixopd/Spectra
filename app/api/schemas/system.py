"""System, admin, health, and configuration schemas."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Shared DTOs live in core to avoid service → API import violations.
# Re-exported here for backward compatibility.
from app.core.schemas import (  # noqa: F401
    AIProviderFallbacks,
    AIProviderProfile,
    AIProviderRouting,
    SettingsUpdateRequest,
    SystemSetupRequest,
    _normalize_ai_provider,
)

# --- Health Schemas ---


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    service: str
    error: str | None = None


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
