"""Helpers for the persisted mission-output read model."""

from __future__ import annotations

from typing import Any

_SEVERITY_KEYS = ("critical", "high", "medium", "low", "info")


def _normalize_severity(value: Any) -> str:
    """Return a supported severity label for downstream consumers."""
    severity = str(value or "").strip().lower()
    if severity not in _SEVERITY_KEYS:
        return "info"
    return severity


def get_mission_summary_dict(mission_or_summary: Any) -> dict[str, Any]:
    """Return the mission summary dict or a safe empty mapping."""
    if isinstance(mission_or_summary, dict):
        return mission_or_summary

    summary = getattr(mission_or_summary, "summary", None)
    if isinstance(summary, dict):
        return summary
    return {}


def get_mission_findings(mission_or_summary: Any) -> list[dict[str, Any]]:
    """Return mission findings from the persisted summary read model."""
    if isinstance(mission_or_summary, dict):
        findings = mission_or_summary.get("findings")
        if isinstance(findings, list):
            return [finding for finding in findings if isinstance(finding, dict)]

        nested_summary = mission_or_summary.get("summary")
        if isinstance(nested_summary, dict):
            findings = nested_summary.get("findings")
        else:
            findings = None
    else:
        summary = get_mission_summary_dict(mission_or_summary)
        findings = summary.get("findings")

    if not isinstance(findings, list):
        return []
    return [finding for finding in findings if isinstance(finding, dict)]


def get_mission_finding_counts(mission_or_summary: Any) -> dict[str, int]:
    """Count mission findings by normalized severity."""
    counts = {severity: 0 for severity in _SEVERITY_KEYS}
    counts["total"] = 0

    for finding in get_mission_findings(mission_or_summary):
        severity = _normalize_severity(finding.get("severity"))
        counts[severity] += 1
        counts["total"] += 1

    return counts


def get_reporter_findings(mission_or_summary: Any) -> list[dict[str, Any]]:
    """Map mission findings into the ReporterInput finding shape."""
    reporter_findings: list[dict[str, Any]] = []

    for finding in get_mission_findings(mission_or_summary):
        source = finding.get("source") or finding.get("tool_source") or finding.get("tool") or ""
        tool_name = finding.get("tool_name") or finding.get("tool_source") or finding.get("tool") or ""
        reporter_findings.append(
            {
                "title": finding.get("title", ""),
                "severity": _normalize_severity(finding.get("severity")),
                "description": finding.get("description", ""),
                "source": source,
                "confirmed": finding.get("confirmed", False),
                "tool_name": tool_name,
            }
        )

    return reporter_findings
