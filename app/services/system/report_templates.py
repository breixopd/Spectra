"""Report template definitions for manual pentest sessions."""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPORT_TEMPLATES: dict[str, dict[str, Any]] = {
    "executive": {
        "name": "Executive Summary",
        "sections": ["overview", "scope", "methodology", "key_findings", "risk_summary", "recommendations"],
    },
    "technical": {
        "name": "Technical Report",
        "sections": ["overview", "scope", "methodology", "findings_detail", "evidence", "remediation", "appendices"],
    },
    "compliance": {
        "name": "Compliance Report",
        "sections": ["overview", "scope", "controls_tested", "findings", "compliance_status", "remediation_timeline"],
    },
}


def list_report_templates() -> list[dict[str, Any]]:
    """Return summary of available report templates."""
    return [{"id": tid, "name": t["name"], "sections": t["sections"]} for tid, t in REPORT_TEMPLATES.items()]


def get_report_template(template_id: str) -> dict[str, Any] | None:
    """Return a report template by ID."""
    t = REPORT_TEMPLATES.get(template_id)
    if t is None:
        return None
    return {"id": template_id, **t}


def generate_report_data(session_path: Path, template_id: str) -> dict[str, Any]:
    """Build report data from session file and template.

    Raises FileNotFoundError if session file doesn't exist.
    Raises ValueError if template_id is unknown.
    """
    template = REPORT_TEMPLATES.get(template_id)
    if template is None:
        raise ValueError(f"Unknown template: {template_id}")

    if not session_path.exists():
        raise FileNotFoundError(f"Session file not found: {session_path}")

    session = json.loads(session_path.read_text())

    findings = session.get("findings", [])
    severity_counts: dict[str, int] = {}
    for f in findings:
        sev = (f.get("severity") or "info").lower()
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    return {
        "template": template_id,
        "template_name": template["name"],
        "sections": template["sections"],
        "session_id": session.get("id", ""),
        "session_name": session.get("name", ""),
        "target": session.get("target", ""),
        "findings": findings,
        "severity_counts": severity_counts,
        "total_findings": len(findings),
        "scope": session.get("scope"),
        "tools_used": session.get("tools_used", []),
        "command_history": session.get("command_history", []),
    }
