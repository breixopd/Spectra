"""Mission and target schemas."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from spectra_platform.models.target import TargetStatus
from spectra_platform.services.mission.types import AttackSurfaceSummary, ToolExecutionRecord


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

    target: str = Field(..., min_length=1, max_length=500, description="Target IP, domain, or URL")
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
    requires_approval: bool | None = Field(
        default=None,
        description="If set, require human approval for high-risk actions; if omitted, uses account default",
    )
    scan_mode: Literal["autonomous", "guided", "manual"] | None = Field(
        default=None,
        description="Steering intensity; if omitted, uses Profile default_scan_mode",
    )
    playbook_id: str | None = Field(
        default=None,
        max_length=128,
        description="Optional adversary simulation playbook id from the catalog",
    )
    authorization_confirmed: bool = Field(
        default=False,
        description="User confirms they own the target or have explicit written authorization to test it",
    )
    vpn_config: str | None = Field(
        default=None,
        max_length=64,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9\-]{0,63}$",
        description="VPN config name to use for this mission",
    )
    pentest_framework: str = Field(
        default="ptes",
        max_length=64,
        description="Built-in methodology checklist (ptes, owasp_top10_2021, network_pentest, api_security, ad_pentest)",
    )

    @field_validator("pentest_framework")
    @classmethod
    def normalize_pentest_framework_id(cls, v: str) -> str:
        from spectra_platform.services.mission.framework_progress import normalize_pentest_framework

        return normalize_pentest_framework(v)

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


class MissionDeleteResponse(BaseModel):
    """Response for mission deletion."""

    status: str
    mission_id: str


class MissionFindingSummary(BaseModel):
    """Summary of a finding within a mission."""

    id: str
    title: str
    severity: str
    status: str
    description: str
    tool_source: str
    created_at: str


class ActionApprovalResponse(BaseModel):
    """Response for action approval/rejection."""

    status: str
    action_id: str
    approved: bool


class MissionResponse(BaseModel):
    """Schema for mission response."""

    id: str
    target: str
    status: str
    current_phase: str | None = None
    logs: list[str]
    directive: str | None = None
    findings: list[dict[str, object]] | None = None
    findings_count: int | None = None
    tools_run: list[str] = Field(default_factory=list)
    tool_executions: list[ToolExecutionRecord] | None = None
    report_path: str | None = None
    attack_surface: AttackSurfaceSummary | None = None
    pentest_framework: str = "ptes"
    framework_label: str = "PTES Standard"
    framework_phase_timeline: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class MissionDetailResponse(MissionResponse):
    """Detailed mission response with summary."""

    directive: str | None = None
    summary: dict[str, object] | None = None
    created_at: str


class PresetResponse(BaseModel):
    """Response model for mission preset configurations."""

    name: str
    description: str
    target_type: str | None = None
    scope: str | None = None
    phases: list[str] = []
    safety_level: str = "standard"
