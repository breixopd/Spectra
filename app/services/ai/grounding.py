"""
Grounding and Anti-Hallucination Framework.

Provides mechanisms to keep LLM agents grounded in reality:
1. Evidence anchoring - forces agents to cite concrete tool output
2. Output verification - validates tool output matches expected patterns
3. Confidence scoring - tracks and decays confidence through the pipeline
4. Structured reasoning - forces step-by-step reasoning with citations
"""

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("spectra.ai.grounding")


# --- Tool Output Validators ---

TOOL_OUTPUT_SIGNATURES: dict[str, list[str]] = {
    "nmap": ["Nmap scan report", "PORT", "STATE", "SERVICE", "<nmaprun"],
    "nuclei": ["[INF]", "[WRN]", "template-id", "matched-at", "info:"],
    "nikto": ["+ Target", "Nikto", "Server:", "OSVDB"],
    "gobuster": ["Status:", "Found:", "/", "Progress:"],
    "ffuf": ["FUZZ", "Status:", "Words:", "Lines:"],
    "sqlmap": ["sqlmap", "Parameter:", "Type:", "Payload:", "---"],
    "hydra": ["Hydra", "login:", "password:", "[DATA]", "host:"],
    "naabu": ["Found", "Host:", "port"],
    "amass": ["FQDN", "Subdomain", "ASN"],
    "wpscan": ["WPScan", "WordPress", "Interesting Finding"],
    "searchsploit": ["Exploit Title", "Path", "----------"],
    "metasploit": ["msf", "exploit", "payload", "session", "Meterpreter"],
}

# Performance Optimization: Pre-compute lowercase signatures to avoid recalculating
# them inside the hot path during output matching.
TOOL_OUTPUT_SIGNATURES_LOWER: dict[str, list[str]] = {
    tool: [sig.lower() for sig in signatures]
    for tool, signatures in TOOL_OUTPUT_SIGNATURES.items()
}


def validate_tool_output(tool_id: str, stdout: str, stderr: str) -> dict[str, Any]:
    """
    Validate that tool output looks legitimate for the given tool.

    Returns dict with:
        - valid: bool - whether output matches expected patterns
        - confidence: float - how confident we are in the output (0-1)
        - issues: list[str] - any problems detected
        - evidence_quality: str - 'strong', 'weak', or 'none'
    """
    output = (stdout + "\n" + stderr).strip()
    issues = []

    if not output:
        return {
            "valid": False,
            "confidence": 0.0,
            "issues": ["Empty output - tool may not have run"],
            "evidence_quality": "none",
        }

    signatures_lower = TOOL_OUTPUT_SIGNATURES_LOWER.get(tool_id.lower(), [])

    if not signatures_lower:
        return {
            "valid": True,
            "confidence": 0.6,
            "issues": ["No signature patterns defined for this tool"],
            "evidence_quality": "weak",
        }

    output_lower = output.lower()
    matches = sum(1 for sig in signatures_lower if sig in output_lower)
    match_ratio = matches / len(signatures_lower) if signatures_lower else 0

    if match_ratio == 0:
        issues.append(f"Output doesn't match any known {tool_id} patterns")
        return {
            "valid": False,
            "confidence": 0.1,
            "issues": issues,
            "evidence_quality": "none",
        }

    if match_ratio < 0.3:
        issues.append(f"Only {matches}/{len(signatures_lower)} signature matches")
        return {
            "valid": True,
            "confidence": 0.4,
            "issues": issues,
            "evidence_quality": "weak",
        }

    return {
        "valid": True,
        "confidence": min(0.5 + match_ratio * 0.5, 1.0),
        "issues": issues,
        "evidence_quality": "strong" if match_ratio >= 0.5 else "weak",
    }


# --- Evidence Extraction ---


def extract_evidence_snippets(
    tool_id: str, stdout: str, max_snippets: int = 5, max_chars: int = 200
) -> list[str]:
    """
    Extract the most relevant evidence lines from tool output.

    Instead of feeding the full output to agents, we extract only the
    meaningful lines (open ports, vulns, credentials, etc.) to keep
    prompts grounded in concrete evidence.
    """
    if not stdout:
        return []

    lines = stdout.strip().split("\n")
    evidence = []

    evidence_patterns = [
        r"\d+/tcp\s+open",  # nmap open ports
        r"\d+/udp\s+open",  # nmap UDP ports
        r"\[critical\]|\[high\]|\[medium\]",  # nuclei severity
        r"CVE-\d{4}-\d+",  # CVE references
        r"login:\s*\S+\s+password:",  # hydra credentials
        r"SQL injection",  # sqlmap findings
        r"VULNERABLE",  # general vuln indicators
        r"\[\+\]",  # success markers
        r"found:|discovered:",  # discovery markers
        r"Status:\s*(200|301|302|403)",  # HTTP status codes (gobuster/ffuf)
    ]

    compiled = [re.compile(p, re.IGNORECASE) for p in evidence_patterns]

    for line in lines:
        line = line.strip()
        if not line or len(line) < 5:
            continue

        for pattern in compiled:
            if pattern.search(line):
                snippet = line[:max_chars]
                if snippet not in evidence:
                    evidence.append(snippet)
                break

        if len(evidence) >= max_snippets:
            break

    return evidence


# --- Reasoning Chain ---


class ReasoningStep(BaseModel):
    """A single step in a reasoning chain with evidence citation."""

    step: int
    claim: str = Field(..., description="What the agent claims/concludes")
    evidence: str = Field(
        ..., description="Concrete evidence supporting this claim (tool output, data)"
    )
    source: str = Field(
        ..., description="Where the evidence came from (tool name, output line)"
    )


class GroundedContext(BaseModel):
    """Context object that forces agents to work with concrete evidence."""

    target: str
    target_type: str
    raw_evidence: list[str] = Field(
        default_factory=list,
        description="Raw evidence snippets from tool outputs",
    )
    confirmed_services: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Services confirmed by tool output (not hallucinated)",
    )
    confirmed_vulns: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Vulnerabilities confirmed by tool output",
    )
    tools_run_with_results: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Tools that ran with their success/failure and evidence quality",
    )

    def get_evidence_summary(self, max_lines: int = 15) -> str:
        """Build a grounded evidence summary for LLM prompts."""
        parts = []

        if self.confirmed_services:
            svc_lines = []
            for svc in self.confirmed_services[:8]:
                port = svc.get("port", "?")
                service = svc.get("service", "unknown")
                product = svc.get("product", "")
                version = svc.get("version", "")
                svc_lines.append(
                    f"  - Port {port}: {service} {product} {version}".strip()
                )
            parts.append(
                "CONFIRMED SERVICES (from tool output):\n" + "\n".join(svc_lines)
            )

        if self.confirmed_vulns:
            vuln_lines = []
            for vuln in self.confirmed_vulns[:5]:
                title = vuln.get("title", "Unknown")
                severity = vuln.get("severity", "info")
                cve = vuln.get("cve_id", "")
                vuln_lines.append(
                    f"  - [{severity.upper()}] {title}" + (f" ({cve})" if cve else "")
                )
            parts.append(
                "CONFIRMED VULNERABILITIES (from tool output):\n"
                + "\n".join(vuln_lines)
            )

        if self.raw_evidence:
            evidence_lines = self.raw_evidence[:max_lines]
            parts.append(
                "RAW EVIDENCE (direct tool output):\n"
                + "\n".join(f"  > {line}" for line in evidence_lines)
            )

        if self.tools_run_with_results:
            tool_lines = []
            for tr in self.tools_run_with_results:
                name = tr.get("tool", "?")
                status = "OK" if tr.get("success") else "FAIL"
                quality = tr.get("evidence_quality", "?")
                tool_lines.append(f"  - {name}: {status} (evidence: {quality})")
            parts.append("TOOL EXECUTION HISTORY:\n" + "\n".join(tool_lines))

        if not parts:
            return "No evidence collected yet. Start with reconnaissance."

        return "\n\n".join(parts)


def build_grounded_context(mission: Any) -> GroundedContext:
    """Build a GroundedContext from a Mission's current state."""
    from app.services.mission.executor.utils import detect_target_type

    ctx = GroundedContext(
        target=mission.target,
        target_type=detect_target_type(mission.target),
    )

    for svc in mission.attack_surface.services:
        ctx.confirmed_services.append(
            {
                "host": svc.host,
                "port": svc.port,
                "service": svc.service,
                "product": svc.product,
                "version": svc.version,
            }
        )

    for vuln in mission.attack_surface.vulnerabilities:
        ctx.confirmed_vulns.append(
            {
                "title": vuln.title,
                "severity": vuln.severity,
                "cve_id": vuln.cve_id,
            }
        )

    for exec_record in getattr(mission, "tool_executions", []):
        ctx.tools_run_with_results.append(
            {
                "tool": exec_record.get("tool_name", "?"),
                "success": exec_record.get("success", False),
                "evidence_quality": exec_record.get("evidence_quality", "unknown"),
            }
        )

    return ctx


# --- Confidence Tracking ---


class ConfidenceTracker:
    """
    Tracks confidence through the pentest pipeline.

    Confidence decays as it passes through stages:
    - Tool reports a finding: initial confidence (0.7-0.9)
    - Consensus validates: maintained or boosted
    - Cross-verified by another tool: boosted to 0.95
    - Failed verification: decayed to 0.3

    Findings below threshold are marked 'unverified' in reports.
    """

    VERIFICATION_BOOST = 0.15
    CONSENSUS_BOOST = 0.1
    FAILURE_DECAY = 0.5
    REPORT_THRESHOLD = 0.4

    def __init__(self):
        self.findings: dict[str, float] = {}

    def register_finding(self, finding_id: str, initial_confidence: float) -> None:
        """Register a new finding with initial confidence."""
        self.findings[finding_id] = min(initial_confidence, 1.0)

    def boost_confidence(self, finding_id: str, reason: str) -> float:
        """Boost confidence after verification."""
        if finding_id not in self.findings:
            return 0.0

        if "cross_verify" in reason:
            self.findings[finding_id] = min(
                self.findings[finding_id] + self.VERIFICATION_BOOST, 1.0
            )
        elif "consensus" in reason:
            self.findings[finding_id] = min(
                self.findings[finding_id] + self.CONSENSUS_BOOST, 1.0
            )

        return self.findings[finding_id]

    def decay_confidence(self, finding_id: str) -> float:
        """Decay confidence after failed verification."""
        if finding_id not in self.findings:
            return 0.0

        self.findings[finding_id] *= self.FAILURE_DECAY
        return self.findings[finding_id]

    def get_verified_findings(self) -> list[str]:
        """Get finding IDs above the report threshold."""
        return [
            fid for fid, conf in self.findings.items() if conf >= self.REPORT_THRESHOLD
        ]

    def get_confidence(self, finding_id: str) -> float:
        """Get current confidence for a finding."""
        return self.findings.get(finding_id, 0.0)
