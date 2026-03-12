"""Mission and target schemas."""

import ipaddress
import re
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.target import TargetStatus

# ---------------------------------------------------------------------------
# SSRF prevention: internal / reserved network ranges
# ---------------------------------------------------------------------------
_INTERNAL_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),  # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]

# Loose patterns for valid domain / IP
_DOMAIN_RE = re.compile(r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z]{2,63}$")
_IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_CIDR_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$")


def is_internal_ip(addr_str: str) -> bool:
    """Return True if *addr_str* resolves to an internal/reserved IP."""
    try:
        addr = ipaddress.ip_address(addr_str)
        return any(addr in net for net in _INTERNAL_NETWORKS)
    except ValueError:
        return False


def is_internal_network(cidr: str) -> bool:
    """Return True if the CIDR block overlaps with internal ranges."""
    try:
        net = ipaddress.ip_network(cidr, strict=False)
        return any(net.overlaps(internal) for internal in _INTERNAL_NETWORKS)
    except ValueError:
        return False


def validate_target_format(target: str) -> str:
    """Validate that *target* is a well-formed IP, CIDR, domain, or URL.

    Returns the cleaned target string or raises ``ValueError``.
    """
    cleaned = "".join(c for c in target.strip() if c.isprintable() or c in " \t")
    if not cleaned:
        raise ValueError("Target cannot be empty")

    # If it looks like a URL, extract the hostname
    host = cleaned
    if "://" in cleaned:
        parsed = urlparse(cleaned)
        host = parsed.hostname or ""
        if not host:
            raise ValueError("Invalid URL: could not extract hostname")

    # Strip port if present (e.g. "10.0.0.1:8080")
    if ":" in host and not host.startswith("["):
        host_no_port = host.rsplit(":", 1)[0]
    else:
        host_no_port = host

    # Validate format: IP, CIDR, or domain
    if _IP_RE.match(host_no_port):
        # Validate it's a real IP
        try:
            ipaddress.ip_address(host_no_port)
        except ValueError:
            raise ValueError(f"Invalid IP address: {host_no_port}")
    elif _CIDR_RE.match(host_no_port):
        try:
            ipaddress.ip_network(host_no_port, strict=False)
        except ValueError:
            raise ValueError(f"Invalid CIDR notation: {host_no_port}")
    elif not _DOMAIN_RE.match(host_no_port):
        raise ValueError("Invalid target format. Provide a valid IP address, CIDR range, domain, or URL.")

    return cleaned


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
    vpn_config: str | None = Field(
        default=None,
        max_length=64,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9\-]{0,63}$",
        description="VPN config name to use for this mission",
    )

    @field_validator("target")
    @classmethod
    def validate_target(cls, v: str) -> str:
        """Validate target format (IP, CIDR, domain, or URL).

        SSRF protection is enforced at the endpoint level (admins may
        target internal addresses; non-admins are blocked there).
        """
        return validate_target_format(v)

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
    created_at: str | None = None

    model_config = ConfigDict(from_attributes=True)


class MissionDetailResponse(MissionResponse):
    """Detailed mission response with summary."""

    directive: str | None = None
    summary: dict | None = None
    created_at: str
