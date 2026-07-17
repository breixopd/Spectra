"""Helpers for the persisted mission-output read model."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import NAMESPACE_URL, uuid5

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
    """Return mission findings with stable IDs from the persisted read model.

    New findings receive a UUID at discovery.  Older persisted summaries did
    not store one, so this read path derives a deterministic UUIDv5 from the
    mission ID and the finding's canonical content.  Callers always receive
    copies: reading legacy data must not mutate the stored JSON document.
    """
    mission_id: str | None = None
    if isinstance(mission_or_summary, dict):
        raw_mission_id = mission_or_summary.get("id")
        mission_id = str(raw_mission_id) if raw_mission_id else None
        findings = mission_or_summary.get("findings")
        if isinstance(findings, list):
            return _with_stable_finding_ids(findings, mission_id)

        nested_summary = mission_or_summary.get("summary")
        findings = nested_summary.get("findings") if isinstance(nested_summary, dict) else None
    else:
        raw_mission_id = getattr(mission_or_summary, "id", None)
        mission_id = str(raw_mission_id) if raw_mission_id else None
        summary = get_mission_summary_dict(mission_or_summary)
        findings = summary.get("findings")

    if not isinstance(findings, list):
        return []
    return _with_stable_finding_ids(findings, mission_id)


def _with_stable_finding_ids(findings: list[Any], mission_id: str | None) -> list[dict[str, Any]]:
    return [_with_stable_finding_id(finding, mission_id) for finding in findings if isinstance(finding, dict)]


def _with_stable_finding_id(finding: dict[str, Any], mission_id: str | None) -> dict[str, Any]:
    result = dict(finding)
    existing_id = result.get("id")
    if isinstance(existing_id, str) and existing_id:
        return result

    # The current endpoint always supplies a mission ID.  The fallback keeps
    # helper use deterministic for report-only mappings that only carry a
    # summary dict, without claiming cross-mission uniqueness.
    namespace = mission_id or "legacy-summary"
    canonical = json.dumps(result, sort_keys=True, default=str, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    result["id"] = str(uuid5(NAMESPACE_URL, f"spectra:mission:{namespace}:finding:{digest}"))
    return result


def get_mission_finding_counts(mission_or_summary: Any) -> dict[str, int]:
    """Count mission findings by normalized severity."""
    counts: dict[str, int] = dict.fromkeys(_SEVERITY_KEYS, 0)
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
