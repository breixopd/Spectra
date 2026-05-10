"""Dynamic pentest framework progress — phase timeline and milestone advancement.

All phase labels, milestone definitions, and ordering come from YAML framework specs.
No hardcoded AssessmentPhase enum references. Framework-driven and tool-agnostic.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from spectra_platform.mission.core.enums import AssessmentPhase
from spectra_platform.services.mission.framework_loader import (
    FrameworkSpec,
    get_default_framework_id,
    get_framework,
    is_valid_framework,
    list_frameworks,
)

logger = logging.getLogger(__name__)


def normalize_pentest_framework(framework_id: str | None) -> str:
    """Return a supported framework id, defaulting to PTES."""
    if is_valid_framework(framework_id):
        return framework_id or get_default_framework_id()
    return get_default_framework_id()


def framework_display_name(framework_id: str | None) -> str:
    """Human-readable label for the framework bound to the mission."""
    spec = get_framework(framework_id)
    return spec.metadata.name


def list_available_frameworks() -> list[dict[str, Any]]:
    """List all available frameworks with metadata for UI / API."""
    return list_frameworks()


def framework_phase_timeline(
    *,
    current_phase: str | None,
    mission_status: str,
    pentest_framework: str | None = None,
) -> list[dict[str, Any]]:
    """Build a phase timeline strip for UI, driven by the active framework spec.

    Each framework defines its own phases, labels, and ordering. The timeline
    marks completed phases as 'done' and the current phase as 'current'.
    """
    spec = get_framework(pentest_framework)
    # Exclude terminal "complete" phase from operational timeline display
    ordered_phases = [
        p for p in sorted(spec.phases, key=lambda p: p.order)
        if p.id != "complete"
    ]

    status = (mission_status or "").lower()
    terminal_ok = status in (
        "completed",
        "exploitation_successful",
        "cancelled",
        "stopped",
        "stopping",
    )

    phase_raw = (current_phase or "").strip().lower()
    cur_id = phase_raw if phase_raw else ordered_phases[0].id

    # Find current phase index
    try:
        cur_idx = next(i for i, p in enumerate(ordered_phases) if p.id == cur_id)
    except StopIteration:
        cur_idx = 0

    if terminal_ok:
        cur_idx = len(ordered_phases)

    out: list[dict[str, Any]] = []
    for i, phase in enumerate(ordered_phases):
        if terminal_ok:
            done, current = True, False
        elif status == "failed":
            done = i < cur_idx
            current = i == cur_idx
        else:
            done = i < cur_idx
            current = i == cur_idx
        out.append(
            {
                "id": phase.id,
                "label": phase.label,
                "description": phase.description,
                "done": done,
                "current": current,
            }
        )
    return out


def framework_milestone_list(pentest_framework: str | None = None) -> list[dict[str, Any]]:
    """List all milestones defined by the framework with their phases."""
    spec = get_framework(pentest_framework)
    return [
        {
            "id": m.id,
            "label": m.label,
            "description": m.description,
            "phase": m.phase,
        }
        for m in spec.milestones
    ]


def advance_milestone(
    mission: Any,
    milestone_id: str,
    status: str = "completed",
    details: str = "",
    pentest_framework: str | None = None,
) -> None:
    """Advance a mission milestone and persist to DB.

    Args:
        mission: Mission object with milestones attribute and pentest_framework
        milestone_id: The milestone ID from the framework spec (e.g., "m1_target_enumeration")
        status: Status to set (default: "completed")
        details: Optional details about the milestone completion
        pentest_framework: Framework ID, defaults to mission's framework
    """
    from sqlalchemy import select

    from spectra_platform.core.database import get_sync_session
    from spectra_platform.models.mission import Mission

    fid = pentest_framework or getattr(mission, "pentest_framework", None)
    spec = get_framework(fid)

    # Look up milestone label from framework spec
    milestone_label = milestone_id
    for m in spec.milestones:
        if m.id == milestone_id:
            milestone_label = m.label
            break

    stored = getattr(mission, "milestones", None) or []
    stored_map = {m.get("milestone"): m for m in stored if m.get("milestone")}

    now = datetime.now(UTC).isoformat()

    entry = {
        "milestone": milestone_id,
        "label": milestone_label,
        "status": status,
        "completed_at": now if status == "completed" else None,
        "details": details,
    }

    stored_map[milestone_id] = entry
    mission.milestones = list(stored_map.values())

    if hasattr(mission, "id") and mission.id:
        session = get_sync_session()
        try:
            result = session.execute(select(Mission).where(Mission.id == mission.id))
            db_mission = result.scalar_one_or_none()
            if db_mission:
                db_mission.milestones = mission.milestones
                session.commit()
        finally:
            session.close()


# ── Backward compatibility wrappers ────────────────────────────────────

def _phase_flow_for_fallback() -> list[str]:
    """Return PTES phase IDs as fallback for code still using AssessmentPhase."""
    spec = get_framework(None)
    return [p.id for p in sorted(spec.phases, key=lambda p: p.order)]
