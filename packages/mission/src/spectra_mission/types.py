"""Typed dictionaries for mission service interfaces.

These replace ``dict[str, Any]`` in function signatures to improve
IDE support and static analysis without changing runtime behaviour.
"""

from __future__ import annotations

from typing import NotRequired

from typing_extensions import TypedDict


class ToolExecutionRecord(TypedDict):
    """Record of a single tool execution within a mission."""

    tool: str
    args: dict[str, object]
    command: str | None
    success: bool
    error: str | None
    timestamp: str


class MissionProgress(TypedDict):
    """Return type for ``Mission.get_progress()``."""

    percent: float
    phase: str
    eta_minutes: NotRequired[float | None]
    completed_tasks: NotRequired[int]
    total_tasks: NotRequired[int]
    active_tasks: NotRequired[list[dict[str, str]]]


class ServiceInfo(TypedDict):
    """Discovered service info returned by ``get_known_services()``."""

    host: str
    port: int
    protocol: str | None
    service: str | None
    product: str | None
    version: str | None


class VulnInfo(TypedDict):
    """Discovered vulnerability info returned by ``get_known_vulns()``."""

    id: str
    name: str
    severity: str
    cve_id: str | None
    cvss: float | None


# Re-exported from canonical definition in app.models.attack_surface
from spectra_persistence.models.attack_surface import AttackSurfaceSummary as AttackSurfaceSummary


class FindingDict(TypedDict, total=False):
    """Structure of a finding recorded by ``Mission.add_finding()``."""

    id: str
    title: str
    description: str
    severity: str
    host: str
    port: int
    service: str
    source: str
    tool_name: str
    confirmed: bool
    proof: str
    cve_id: str
    cvss: float
    location: str
    recommendation: str
    count: int
    created_at: str
    evidence: dict[str, object]
    evidence_bundle: dict[str, object]


class MissionListItem(TypedDict):
    """Single mission item returned by ``list_missions()``."""

    id: str
    target: str
    status: str
    directive: str
    start_time: str | None
    findings_count: int
    tools_run_count: int


class TokenUsage(TypedDict, total=False):
    """Token count structure for LLM cost tracking."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
