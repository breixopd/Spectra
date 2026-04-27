"""Tool output processing, result logging, and attack surface updates."""

from __future__ import annotations

import logging
import re
import shutil
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.infrastructure.paths import data_path

if TYPE_CHECKING:
    from app.services.mission.mission import Mission
    from app.services.tools.models import ToolExecutionResult

logger = logging.getLogger(__name__)

# --- Tool name helpers -------------------------------------------------------

_TOOL_ALIASES: dict[str, str] = {
    "metasploit framework": "metasploit",
    "metasploit": "metasploit",
    "hydra": "hydra",
    "nuclei": "nuclei",
    "nmap": "nmap",
    "nikto": "nikto",
    "gobuster": "gobuster",
    "wpscan": "wpscan",
    "sqlmap": "sqlmap",
    "searchsploit": "searchsploit",
    "ffuf": "ffuf",
    "naabu": "naabu",
    "amass": "amass",
}


def normalize_tool_name(tool_name: str) -> str:
    """Normalize tool names to match plugin IDs.

    LLMs often use title-case like ``Metasploit Framework`` but plugin IDs are
    lowercase.
    """
    normalized = tool_name.lower().strip()
    return _TOOL_ALIASES.get(normalized, normalized)


def validate_tool_name(tool_name: str) -> bool:
    """Validate tool name for filesystem safety."""
    return bool(re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", tool_name))


def prepare_output_directory(mission_id: str, run_id: str) -> Path:
    """Create and return the output directory path."""
    path = data_path("missions", mission_id, "scans", run_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


async def persist_output_directory(mission_id: str, output_dir: str | Path) -> int:
    """Persist transient scan artifacts to S3 storage.

    Returns the total number of bytes uploaded.
    """
    from app.core.config import settings
    from app.services.storage import get_storage_service

    storage = get_storage_service()
    root = Path(output_dir)
    if not root.exists():
        return 0

    total_bytes = 0
    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        total_bytes += file_path.stat().st_size
        rel_path = file_path.relative_to(root)
        key = f"{mission_id}/scans/{root.name}/{rel_path.as_posix()}"
        await storage.upload_file(settings.S3_BUCKET_MISSIONS, key, file_path)

    return total_bytes


def cleanup_output_directory(output_dir: str | Path) -> None:
    """Delete a transient scan output directory if it exists."""
    path = Path(output_dir)
    if not path.exists():
        return
    shutil.rmtree(path, ignore_errors=True)


def cleanup_mission_workspace(mission_id: str) -> None:
    """Delete the local mission workspace after artifacts have been uploaded to S3."""
    workspace = data_path("missions", mission_id)
    if workspace.exists():
        shutil.rmtree(workspace, ignore_errors=True)


def create_error_result(tool_id: str, target: str, error: str) -> ToolExecutionResult:
    from app.services.tools.models import ToolExecutionResult as _TER

    return _TER(
        tool_id=tool_id,
        target=target,
        success=False,
        stdout="",
        stderr=str(error),
        exit_code=-1,
        duration_seconds=0.0,
    )


# --- Post-execution logging --------------------------------------------------


def log_success(mission: Mission, tool_name: str, result: ToolExecutionResult) -> None:
    """Log detailed successful execution summary."""
    finding_count = len(result.parsed_findings)
    summary_parts: list[str] = []
    details: list[str] = []

    if finding_count > 0:
        findings = result.parsed_findings

        # Collect open ports (nmap, naabu style)
        open_ports = [f.get("port") for f in findings if f.get("state") == "open" and f.get("port")]
        if open_ports:
            summary_parts.append(f"{len(open_ports)} open port(s)")
            details.append(f"Ports: {', '.join(str(p) for p in open_ports[:10])}")
            if len(open_ports) > 10:
                details[-1] += f"... (+{len(open_ports) - 10} more)"

        # Collect services discovered
        services = [
            f"{f.get('service', 'unknown')}:{f.get('port')}" for f in findings if f.get("service") and f.get("port")
        ]
        if services and len(services) <= 8:
            details.append(f"Services: {', '.join(services)}")
        elif services:
            details.append(f"Services: {len(services)} discovered")

        # Collect vulnerabilities (nuclei, nikto style)
        vulns = [
            f
            for f in findings
            if f.get("severity") or (f.get("info", {}) if isinstance(f.get("info"), dict) else {}).get("severity")
        ]
        if vulns:
            sev_counts: dict[str, int] = {}
            for v in vulns:
                sev = (
                    v.get("severity")
                    or (v.get("info", {}) if isinstance(v.get("info"), dict) else {}).get("severity")
                    or "info"
                )
                sev_counts[sev.lower()] = sev_counts.get(sev.lower(), 0) + 1

            sev_strs = []
            for sev in ["critical", "high", "medium", "low", "info"]:
                if sev in sev_counts:
                    sev_strs.append(f"{sev_counts[sev]} {sev}")

            summary_parts.append(f"{len(vulns)} vulnerability finding(s)")
            if sev_strs:
                details.append(f"Severity: {', '.join(sev_strs)}")

            # Show top 3 vulnerability names
            vuln_names = [
                v.get("name")
                or (v.get("info", {}) if isinstance(v.get("info"), dict) else {}).get("name")
                or v.get("template-id", "")
                for v in vulns[:3]
            ]
            vuln_names = [n for n in vuln_names if n]
            if vuln_names:
                details.append(f"Found: {', '.join(vuln_names)}")

        # Collect directories/files (gobuster, ffuf style)
        dirs = [
            f.get("url") or f.get("path") for f in findings if f.get("status") in (200, 301, 302, 403) or f.get("words")
        ]
        if dirs and not open_ports and not vulns:
            summary_parts.append(f"{len(dirs)} path(s) discovered")
            if len(dirs) <= 5:
                details.append(f"Paths: {', '.join(str(d) for d in dirs)}")

        # Collect credentials (hydra style)
        creds = [f for f in findings if f.get("login") or f.get("password")]
        if creds:
            summary_parts.append(f"{len(creds)} credential(s) found")
            details.append("Valid credentials discovered!")

        # Fallback
        if not summary_parts:
            summary_parts.append(f"{finding_count} finding(s)")
    else:
        summary_parts.append("scan complete, no findings")

    summary_str = ", ".join(summary_parts)
    duration_str = f" ({result.duration_seconds:.1f}s)" if result.duration_seconds else ""

    mission.log(f"[OK] {tool_name}{duration_str}: {summary_str}")
    for detail in details[:4]:
        mission.log(f"    -> {detail}")


# --- Attack surface updates --------------------------------------------------


def update_attack_surface_from_finding(mission: Mission, finding: dict[str, Any]) -> None:
    """Update attack surface from a parsed finding."""
    # Handle nmap-style port/service findings
    if finding.get("port") or finding.get("portid"):
        port = finding.get("port") or finding.get("portid")
        try:
            port = int(port or 0)
            mission.add_service(
                host=finding.get("ip") or finding.get("host") or mission.target,
                port=port,
                service=finding.get("service") or finding.get("name"),
                product=finding.get("product"),
                version=finding.get("version"),
            )
        except (ValueError, TypeError):
            pass

    # Handle vulnerability findings (from nuclei, etc.)
    _raw_info = finding.get("info")
    info: dict[str, Any] = _raw_info if isinstance(_raw_info, dict) else {}
    severity = finding.get("severity") or info.get("severity")
    name = finding.get("name") or info.get("name") or finding.get("template-id")

    if severity and name and severity.lower() in ("info", "low", "medium", "high", "critical"):
        _raw_cls = info.get("classification")
        classification: dict[str, Any] = _raw_cls if isinstance(_raw_cls, dict) else {}
        cve_id = finding.get("cve_id") or classification.get("cve-id")
        if isinstance(cve_id, list):
            cve_id = cve_id[0] if cve_id else None

        mission.add_vulnerability(
            vuln_id=finding.get("template-id") or f"vuln-{uuid.uuid4().hex[:8]}",
            title=name,
            severity=severity,
            cve_id=cve_id,
        )

    # Handle web app findings
    url = finding.get("url") or finding.get("matched-at")
    if url and (finding.get("technologies") or finding.get("matcher-name")):
        techs = finding.get("technologies") or []
        if finding.get("matcher-name"):
            techs.append(finding.get("matcher-name"))
        mission.add_webapp(url=url, technologies=techs)


# --- Memory recording --------------------------------------------------------


def record_to_memory(
    mission: Mission,
    tool_name: str,
    target: str,
    args: dict[str, Any] | None,
    result: ToolExecutionResult,
) -> None:
    """Record tool execution results to persistent memory for learning."""
    try:
        from app.services.ai.memory import detect_os_from_output, get_memory

        memory = get_memory(mission.user_id)

        # Determine service context from mission's attack surface
        service = "unknown"
        product = None
        version = None
        for svc in mission.attack_surface.services:
            if str(svc.port) in target or svc.host in target:
                service = svc.service or "unknown"
                product = svc.product
                version = svc.version
                break
        if service == "unknown" and mission.attack_surface.services:
            svc = mission.attack_surface.services[0]
            service = svc.service or "unknown"
            product = svc.product
            version = svc.version

        # Detect OS from output if this is nmap or similar
        detected_os = None
        if result.stdout and tool_name in ("nmap", "naabu"):
            detected_os = detect_os_from_output(result.stdout)
            if detected_os and detected_os != "unknown":
                mission.log(f"[LEARN] Detected OS: {detected_os}")
                if not getattr(mission, "_detected_os", None):
                    mission._detected_os = detected_os  # type: ignore[attr-defined]
                    memory.update_target_profile(
                        detected_os,
                        services=[service] if service != "unknown" else [],
                    )

        os_family = getattr(mission, "_detected_os", None) or detected_os

        # Record finding types
        finding_types: list[str] = []
        for f in result.parsed_findings:
            ft = f.get("severity") or f.get("state") or f.get("type", "info")
            if ft not in finding_types:
                finding_types.append(ft)

        memory.record_tool_result(
            tool_id=tool_name,
            target_service=service,
            success=result.success and len(result.parsed_findings) > 0,
            findings_count=len(result.parsed_findings),
            finding_types=finding_types,
            target_product=product,
            target_version=version,
            target_os=os_family,
            args_used=args or {},
        )

        # Update target profile with effective/ineffective tools
        if os_family and os_family != "unknown":
            if result.success and result.parsed_findings:
                memory.update_target_profile(os_family, effective_tools=[tool_name])
            elif not result.success:
                memory.update_target_profile(os_family, ineffective_tools=[tool_name])

    except (OSError, RuntimeError, ValueError) as e:
        logger.warning("Memory recording failed: %s", e)
