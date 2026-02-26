"""
Pydantic schemas for API requests and responses.

Provides input validation and serialization for all API endpoints.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    record_demo: bool = Field(
        default=False,
        description="Record a video walkthrough of the exploit workflow if exploitation succeeds",
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


class SystemSetupRequest(BaseModel):
    """Schema for system setup."""

    user: UserCreate
    llm_provider: str = Field(..., pattern="^(ollama|api)$")
    llm_model: str
    llm_api_key: str | None = None
    llm_api_base: str | None = None
    ollama_host: str | None = None
    # Infrastructure options
    use_custom_db: bool = False
    database_url: str | None = None
    use_custom_redis: bool = False
    redis_host: str | None = None
    redis_port: str | None = None
    redis_password: str | None = None


class LLMTestRequest(BaseModel):
    """Schema for testing LLM connection."""

    provider: str
    model: str
    api_key: str | None = None
    base_url: str | None = None
    ollama_host: str | None = None
