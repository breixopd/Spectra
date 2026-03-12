"""Data models for Persistent Mission Memory."""

from typing import Any

from pydantic import BaseModel, Field


class ToolLesson(BaseModel):
    """What we learned from running a tool."""

    tool_id: str
    target_service: str
    target_product: str | None = None
    target_version: str | None = None
    target_os: str | None = None
    args_used: dict[str, Any] = Field(default_factory=dict)
    success: bool = True
    findings_count: int = 0
    finding_types: list[str] = Field(default_factory=list)
    notes: str = ""
    timestamp: str = ""


class ExploitLesson(BaseModel):
    """A successful exploit chain to remember."""

    target_service: str
    target_product: str | None = None
    target_version: str | None = None
    target_os: str | None = None
    exploit_tool: str
    exploit_args: dict[str, Any] = Field(default_factory=dict)
    payload_type: str | None = None
    access_level: str = "unknown"
    attack_chain: list[str] = Field(default_factory=list)
    cve_id: str | None = None
    timestamp: str = ""


class TargetProfile(BaseModel):
    """Learned profile for a target type."""

    os_family: str  # linux, windows, macos, freebsd, embedded, unknown
    os_version: str | None = None
    arch: str | None = None
    services: list[str] = Field(default_factory=list)
    effective_tools: list[str] = Field(default_factory=list)
    ineffective_tools: list[str] = Field(default_factory=list)
    effective_exploits: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# --- OS Detection ---

OS_SIGNATURES = {
    "linux": [
        "Linux",
        "Ubuntu",
        "Debian",
        "CentOS",
        "RedHat",
        "Fedora",
        "Kali",
        "Alpine",
        "Arch",
        "SUSE",
        "Gentoo",
        "Mint",
    ],
    "windows": [
        "Windows",
        "Microsoft",
        "IIS",
        "NTLM",
        "SMB",
        "Active Directory",
        "PowerShell",
        "Win32",
        "Win64",
        ".NET",
    ],
    "macos": ["macOS", "Darwin", "Apple", "OS X"],
    "freebsd": ["FreeBSD", "OpenBSD", "NetBSD", "pfSense"],
    "embedded": [
        "MikroTik",
        "Cisco",
        "Juniper",
        "FortiOS",
        "DD-WRT",
        "OpenWrt",
        "RTOS",
        "VxWorks",
        "firmware",
    ],
}

# Performance Optimization: Pre-compute lowercase signatures to avoid recalculating
# them inside the hot path during output matching.
OS_SIGNATURES_LOWER: dict[str, list[str]] = {
    os_family: [sig.lower() for sig in signatures] for os_family, signatures in OS_SIGNATURES.items()
}


def detect_os_from_output(output: str) -> str:
    """Detect OS family from tool output (nmap banners, etc.)."""
    output_lower = output.lower()

    scores: dict[str, int] = {}
    for os_family, signatures in OS_SIGNATURES_LOWER.items():
        score = sum(1 for sig in signatures if sig in output_lower)
        if score > 0:
            scores[os_family] = score

    if not scores:
        return "unknown"

    return max(scores, key=scores.get)  # type: ignore[arg-type]


def detect_os_from_services(services: list[dict[str, Any]]) -> str:
    """Detect OS family from discovered services."""
    all_text = " ".join(f"{s.get('product', '')} {s.get('version', '')} {s.get('service', '')}" for s in services)
    return detect_os_from_output(all_text)
