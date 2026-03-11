"""Mission and target schemas."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.target import TargetStatus


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
