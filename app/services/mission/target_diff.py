"""
Target Diff / Change Detection Service.

Compares scan results across mission runs to detect changes:
- New / removed services
- New / resolved findings
- New / patched vulnerabilities

Used by the ``GET /missions/{id1}/diff/{id2}`` API endpoint.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("spectra.mission.target_diff")


def _service_key(svc: dict[str, Any]) -> str:
    """Stable identity key for a discovered service."""
    host = svc.get("host") or svc.get("ip") or ""
    port = str(svc.get("port") or svc.get("portid") or "")
    proto = svc.get("protocol") or svc.get("proto") or "tcp"
    return f"{host}:{port}/{proto}"


def _finding_key(finding: dict[str, Any]) -> str:
    """Stable identity key for a finding."""
    template = finding.get("template-id") or finding.get("name") or ""
    host = finding.get("host") or finding.get("ip") or ""
    port = str(finding.get("port") or finding.get("portid") or "")
    matched = finding.get("matched-at") or ""
    return f"{template}|{host}|{port}|{matched}"


def _vuln_key(vuln: dict[str, Any]) -> str:
    """Stable identity key for a vulnerability."""
    vid = vuln.get("id") or vuln.get("vuln_id") or ""
    cve = vuln.get("cve_id") or ""
    return f"{vid}|{cve}"


def _extract_services(mission: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the service list out of a mission dict."""
    attack_surface = mission.get("attack_surface") or {}
    services = attack_surface.get("services") or []
    if not services:
        summary = mission.get("summary") or {}
        services = summary.get("services") or []
    return services


def _extract_findings(mission: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the findings list out of a mission dict."""
    findings = mission.get("findings") or []
    if not findings:
        summary = mission.get("summary") or {}
        findings = summary.get("findings") or []
    return findings


def _extract_vulns(mission: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the vulnerability list out of a mission dict."""
    attack_surface = mission.get("attack_surface") or {}
    vulns = attack_surface.get("vulnerabilities") or []
    if not vulns:
        summary = mission.get("summary") or {}
        vulns = summary.get("vulnerabilities") or []
    return vulns


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compare_missions(
    old_mission: dict[str, Any],
    new_mission: dict[str, Any],
) -> dict[str, Any]:
    """Compare two mission snapshots and return a structured diff.

    Returns a dict with:
    - ``new_services``: services present in *new_mission* but not *old_mission*
    - ``removed_services``: services present in *old_mission* but not *new_mission*
    - ``new_findings``: findings present in *new_mission* but not *old_mission*
    - ``resolved_findings``: findings present in *old_mission* but not *new_mission*
    - ``new_vulns``: vulnerabilities present in *new_mission* but not *old_mission*
    - ``patched_vulns``: vulnerabilities present in *old_mission* but not *new_mission*
    """
    old_services = _extract_services(old_mission)
    new_services = _extract_services(new_mission)
    old_svc_map = {_service_key(s): s for s in old_services}
    new_svc_map = {_service_key(s): s for s in new_services}

    old_findings = _extract_findings(old_mission)
    new_findings = _extract_findings(new_mission)
    old_find_map = {_finding_key(f): f for f in old_findings}
    new_find_map = {_finding_key(f): f for f in new_findings}

    old_vulns = _extract_vulns(old_mission)
    new_vulns = _extract_vulns(new_mission)
    old_vuln_map = {_vuln_key(v): v for v in old_vulns}
    new_vuln_map = {_vuln_key(v): v for v in new_vulns}

    return {
        "new_services": [
            new_svc_map[k] for k in new_svc_map if k not in old_svc_map
        ],
        "removed_services": [
            old_svc_map[k] for k in old_svc_map if k not in new_svc_map
        ],
        "new_findings": [
            new_find_map[k] for k in new_find_map if k not in old_find_map
        ],
        "resolved_findings": [
            old_find_map[k] for k in old_find_map if k not in new_find_map
        ],
        "new_vulns": [
            new_vuln_map[k] for k in new_vuln_map if k not in old_vuln_map
        ],
        "patched_vulns": [
            old_vuln_map[k] for k in old_vuln_map if k not in new_vuln_map
        ],
    }


def generate_diff_report(diff: dict[str, Any]) -> str:
    """Generate a human-readable Markdown summary of a mission diff."""
    lines: list[str] = ["# Mission Diff Report", ""]

    # --- Services ---
    new_svcs = diff.get("new_services") or []
    removed_svcs = diff.get("removed_services") or []
    lines.append("## Services")
    lines.append("")
    if new_svcs:
        lines.append(f"### New Services ({len(new_svcs)})")
        lines.append("")
        for s in new_svcs:
            host = s.get("host") or "?"
            port = s.get("port") or "?"
            svc = s.get("service") or "unknown"
            product = s.get("product") or ""
            version = s.get("version") or ""
            desc = f"{product} {version}".strip() or svc
            lines.append(f"- **{host}:{port}** — {desc}")
        lines.append("")
    if removed_svcs:
        lines.append(f"### Removed Services ({len(removed_svcs)})")
        lines.append("")
        for s in removed_svcs:
            host = s.get("host") or "?"
            port = s.get("port") or "?"
            svc = s.get("service") or "unknown"
            lines.append(f"- ~~{host}:{port}~~ — {svc}")
        lines.append("")
    if not new_svcs and not removed_svcs:
        lines.append("No service changes detected.")
        lines.append("")

    # --- Findings ---
    new_finds = diff.get("new_findings") or []
    resolved = diff.get("resolved_findings") or []
    lines.append("## Findings")
    lines.append("")
    if new_finds:
        lines.append(f"### New Findings ({len(new_finds)})")
        lines.append("")
        for f in new_finds:
            name = f.get("template-id") or f.get("name") or "unnamed"
            info = f.get("info") if isinstance(f.get("info"), dict) else {}
            sev = f.get("severity") or info.get("severity") or "?"
            host = f.get("host") or f.get("ip") or ""
            lines.append(f"- **{name}** [{sev}] @ {host}")
        lines.append("")
    if resolved:
        lines.append(f"### Resolved Findings ({len(resolved)})")
        lines.append("")
        for f in resolved:
            name = f.get("template-id") or f.get("name") or "unnamed"
            lines.append(f"- ~~{name}~~")
        lines.append("")
    if not new_finds and not resolved:
        lines.append("No finding changes detected.")
        lines.append("")

    # --- Vulnerabilities ---
    new_vulns = diff.get("new_vulns") or []
    patched = diff.get("patched_vulns") or []
    lines.append("## Vulnerabilities")
    lines.append("")
    if new_vulns:
        lines.append(f"### New Vulnerabilities ({len(new_vulns)})")
        lines.append("")
        for v in new_vulns:
            title = v.get("title") or v.get("name") or v.get("id") or "?"
            sev = v.get("severity") or "?"
            cve = v.get("cve_id") or ""
            cve_str = f" ({cve})" if cve else ""
            lines.append(f"- **{title}** [{sev}]{cve_str}")
        lines.append("")
    if patched:
        lines.append(f"### Patched Vulnerabilities ({len(patched)})")
        lines.append("")
        for v in patched:
            title = v.get("title") or v.get("name") or v.get("id") or "?"
            lines.append(f"- ~~{title}~~")
        lines.append("")
    if not new_vulns and not patched:
        lines.append("No vulnerability changes detected.")
        lines.append("")

    return "\n".join(lines)
