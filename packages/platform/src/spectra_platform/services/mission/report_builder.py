"""Framework-driven report builder — generates reports from mission findings.

Each framework defines its own report sections and ordering. The builder
iterates the framework's report_sections and assembles findings accordingly.
Outputs JSON, Markdown, and HTML formats.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from spectra_platform.services.mission.framework_loader import FrameworkSpec, get_framework

logger = logging.getLogger(__name__)


def build_report(
    mission: Any,
    findings: list[dict[str, Any]],
    *,
    format: str = "json",
) -> dict[str, Any] | str:
    """Build a framework-driven report from mission findings.

    Args:
        mission: Mission object with pentest_framework attribute
        findings: List of finding dicts with severity, description, evidence
        format: Output format (json, markdown, html)

    Returns:
        Report as dict (json) or string (markdown/html)
    """
    framework_id = getattr(mission, "pentest_framework", "ptes")
    spec = get_framework(framework_id)

    sections = sorted(spec.report_sections, key=lambda s: s.order)
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    sorted_findings = sorted(findings, key=lambda f: severity_order.get(f.get("severity", "info"), 99))

    report = {
        "metadata": {
            "framework": spec.metadata.name,
            "framework_version": spec.metadata.version,
            "mission_id": getattr(mission, "id", ""),
            "target": getattr(mission, "target", ""),
            "generated_at": datetime.now(UTC).isoformat(),
        },
        "sections": {},
    }

    for section in sections:
        report["sections"][section.id] = _build_section(
            section.id, section.label, spec, mission, sorted_findings
        )

    if format == "markdown":
        return _to_markdown(report, spec, sorted_findings)
    elif format == "html":
        return _to_html(report, spec, sorted_findings)
    return report


def _build_section(
    section_id: str,
    label: str,
    spec: FrameworkSpec,
    mission: Any,
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a single report section."""
    section = {"label": label}

    if section_id == "executive_summary":
        critical = sum(1 for f in findings if f.get("severity") == "critical")
        high = sum(1 for f in findings if f.get("severity") == "high")
        medium = sum(1 for f in findings if f.get("severity") == "medium")
        section["content"] = (
            f"Assessment of {getattr(mission, 'target', 'target')} found "
            f"{critical} critical, {high} high, and {medium} medium severity findings."
        )
        section["summary"] = {"critical": critical, "high": high, "medium": medium}

    elif section_id == "methodology":
        section["content"] = (
            f"This assessment followed {spec.metadata.name} v{spec.metadata.version} "
            f"methodology ({spec.metadata.description})."
        )

    elif section_id == "scope":
        section["content"] = f"Target: {getattr(mission, 'target', 'Not specified')}"
        section["directive"] = getattr(mission, "directive", "")

    elif section_id in ("findings_summary", "findings", "detailed_findings"):
        section["findings"] = [
            {
                "title": f.get("name") or f.get("title", "Untitled Finding"),
                "severity": f.get("severity", "info"),
                "description": f.get("description", ""),
                "evidence": f.get("evidence", ""),
                "remediation": f.get("remediation", ""),
                "cve": f.get("cve", ""),
            }
            for f in findings
        ]

    elif section_id == "remediation":
        section["remediations"] = [
            f.get("remediation", "Apply vendor patch and follow security best practices")
            for f in findings
            if f.get("remediation")
        ]

    elif section_id == "exploit_chain":
        tools = getattr(mission, "tools_run", []) or []
        section["exploit_chain"] = tools

    elif section_id == "appendices":
        section["tools_used"] = getattr(mission, "tools_run", []) or []
        section["framework"] = spec.metadata.name

    return section


def _to_markdown(report: dict, spec: FrameworkSpec, findings: list) -> str:
    """Convert report to Markdown."""
    lines = [f"# Security Assessment Report", ""]
    meta = report["metadata"]
    lines.append(f"**Framework:** {meta['framework']} v{meta['framework_version']}")
    lines.append(f"**Target:** {meta['target']}")
    lines.append(f"**Date:** {meta['generated_at']}")
    lines.append("")

    for section_id, section in report["sections"].items():
        lines.append(f"## {section['label']}")
        if "content" in section:
            lines.append(section["content"])
        if "findings" in section:
            for f in section["findings"]:
                lines.append(f"\n### {f['title']}")
                lines.append(f"**Severity:** {f['severity']}")
                lines.append(f"**Description:** {f['description']}")
                if f.get("remediation"):
                    lines.append(f"**Remediation:** {f['remediation']}")
        lines.append("")
    return "\n".join(lines)


def _to_html(report: dict, spec: FrameworkSpec, findings: list) -> str:
    """Convert report to HTML."""
    md = _to_markdown(report, spec, findings)
    # Simple Markdown to HTML converter (for basic formatting)
    html_lines = ["<html><body>"]
    for line in md.split("\n"):
        if line.startswith("# "):
            html_lines.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            html_lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("### "):
            html_lines.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("**") and ":**" in line:
            html_lines.append(f"<p><strong>{line.replace('**', '')}</strong></p>")
        elif line:
            html_lines.append(f"<p>{line}</p>")
    html_lines.append("</body></html>")
    return "\n".join(html_lines)
