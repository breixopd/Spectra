"""Pentest framework metadata and PTES-aligned phase timeline for API / UI."""

from __future__ import annotations

from typing import Any

from spectra_platform.mission.core.enums import AssessmentPhase
from spectra_platform.services.system.checklists import BUILTIN_CHECKLISTS

ALLOWED_PENTEST_FRAMEWORKS: frozenset[str] = frozenset(BUILTIN_CHECKLISTS.keys())

# Operational phases shown in mission details (before terminal COMPLETE).
_PHASE_FLOW: tuple[AssessmentPhase, ...] = (
    AssessmentPhase.SCOPE,
    AssessmentPhase.DISCOVERY,
    AssessmentPhase.ENUMERATION,
    AssessmentPhase.VULNERABILITY,
    AssessmentPhase.EXPLOITATION,
    AssessmentPhase.POST_EXPLOITATION,
    AssessmentPhase.REPORTING,
)

_PHASE_LABELS: dict[str, str] = {
    AssessmentPhase.SCOPE.value: "Scope & authorization",
    AssessmentPhase.DISCOVERY.value: "Discovery / OSINT",
    AssessmentPhase.ENUMERATION.value: "Enumeration",
    AssessmentPhase.VULNERABILITY.value: "Vulnerability analysis",
    AssessmentPhase.EXPLOITATION.value: "Exploitation",
    AssessmentPhase.POST_EXPLOITATION.value: "Post-exploitation",
    AssessmentPhase.REPORTING.value: "Reporting",
    AssessmentPhase.COMPLETE.value: "Complete",
}


def normalize_pentest_framework(framework_id: str | None) -> str:
    """Return a supported checklist id, defaulting to PTES."""
    if framework_id and framework_id in ALLOWED_PENTEST_FRAMEWORKS:
        return framework_id
    return "ptes"


def framework_display_name(framework_id: str | None) -> str:
    """Human label for the methodology checklist bound to the mission."""
    fid = normalize_pentest_framework(framework_id)
    meta = BUILTIN_CHECKLISTS.get(fid) or {}
    return str(meta.get("name") or fid.replace("_", " ").title())


def framework_phase_timeline(
    *,
    current_phase: str | None,
    mission_status: str,
    pentest_framework: str | None = None,
) -> list[dict[str, Any]]:
    """Build a fixed-order phase strip for UI (PTES-aligned assessment phases).

    ``pentest_framework`` selects the checklist name elsewhere; the phase strip
    stays on ``AssessmentPhase`` so it matches the live planner regardless of
    checklist (OWASP / network / PTES all map to the same execution phases).
    """
    _ = normalize_pentest_framework(pentest_framework)  # validate id; strip uses phases below

    status = (mission_status or "").lower()
    terminal_ok = status in (
        "completed",
        "exploitation_successful",
        "cancelled",
        "stopped",
        "stopping",
    )

    phase_raw = (current_phase or "").strip().lower()
    try:
        cur = AssessmentPhase(phase_raw) if phase_raw else AssessmentPhase.SCOPE
    except ValueError:
        cur = AssessmentPhase.SCOPE

    if cur == AssessmentPhase.COMPLETE or terminal_ok:
        cur_idx = len(_PHASE_FLOW)
    else:
        cur_idx = next((i for i, p in enumerate(_PHASE_FLOW) if p == cur), 0)

    out: list[dict[str, Any]] = []
    for i, p in enumerate(_PHASE_FLOW):
        if terminal_ok or cur == AssessmentPhase.COMPLETE:
            done, current = True, False
        elif status == "failed":
            done = i < cur_idx
            current = i == cur_idx
        else:
            done = i < cur_idx
            current = i == cur_idx
        out.append(
            {
                "id": p.value,
                "label": _PHASE_LABELS.get(p.value, p.value),
                "done": done,
                "current": current,
            }
        )
    return out
