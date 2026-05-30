"""Typed facts extracted by perceptors from tool output.

These are the structured data types that flow from perceptors → planner graph.
Each fact type has a well-defined schema for reliable machine consumption.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DiscoveredHost:
    """A discovered network host."""
    ip: str
    hostname: str = ""
    os: str = ""
    os_confidence: int = 0  # 0-100
    mac: str = ""
    status: str = "up"  # up, down, filtered
    source_tool: str = ""


@dataclass
class DiscoveredPort:
    """An open/filtered port on a host."""
    host_ip: str
    port: int
    protocol: str = "tcp"  # tcp, udp
    state: str = "open"  # open, closed, filtered
    service_name: str = ""
    service_product: str = ""
    service_version: str = ""
    service_extra: str = ""
    source_tool: str = ""


@dataclass
class DiscoveredService:
    """A service identified on a port with version details."""
    host_ip: str
    port: int
    protocol: str = "tcp"
    name: str = ""
    product: str = ""
    version: str = ""
    extra_info: str = ""
    cpe: str = ""
    source_tool: str = ""


@dataclass
class DiscoveredVulnerability:
    """A vulnerability found by scanning tools."""
    host_ip: str
    port: int = 0
    vuln_id: str = ""  # CVE, template ID, etc.
    name: str = ""
    description: str = ""
    severity: str = ""  # critical, high, medium, low, info
    cvss_score: float = 0.0
    matched_at: str = ""  # URL or endpoint where found
    evidence: str = ""
    remediation: str = ""
    source_tool: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class ExploitResult:
    """Result of an exploit attempt."""
    host_ip: str
    port: int = 0
    exploit_name: str = ""
    success: bool = False
    shell_type: str = ""  # reverse_shell, bind_shell, meterpreter, webshell
    evidence: str = ""  # Screenshot, command output, etc.
    credentials: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    source_tool: str = ""
    duration_seconds: float = 0.0
