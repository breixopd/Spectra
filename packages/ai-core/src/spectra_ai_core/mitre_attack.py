"""
MITRE ATT&CK Mapping Service.

Maps security tool executions and findings to MITRE ATT&CK TTP IDs.
Provides:
- Auto-tagging of findings with ATT&CK technique IDs
- ATT&CK Navigator JSON export for layer visualization
- Tactic coverage summary across findings
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ATT&CK Tactic metadata (ID → display name)
# ---------------------------------------------------------------------------
TACTIC_NAMES: dict[str, str] = {
    "TA0043": "Reconnaissance",
    "TA0042": "Resource Development",
    "TA0001": "Initial Access",
    "TA0002": "Execution",
    "TA0003": "Persistence",
    "TA0004": "Privilege Escalation",
    "TA0005": "Defense Evasion",
    "TA0006": "Credential Access",
    "TA0007": "Discovery",
    "TA0008": "Lateral Movement",
    "TA0009": "Collection",
    "TA0010": "Exfiltration",
    "TA0011": "Command and Control",
    "TA0040": "Impact",
}

# ---------------------------------------------------------------------------
# Technique → tactic mapping (subset relevant to Spectra's tooling)
# ---------------------------------------------------------------------------
TECHNIQUE_TACTICS: dict[str, list[str]] = {
    "T1046": ["TA0007"],
    "T1595.002": ["TA0043"],
    "T1083": ["TA0007"],
    "T1110.001": ["TA0006"],
    "T1190": ["TA0001"],
    "T1588.005": ["TA0042"],
    "T1203": ["TA0002"],
    "T1003": ["TA0006"],
    "T1068": ["TA0004"],
    "T1021": ["TA0008"],
    "T1041": ["TA0010"],
}

# ---------------------------------------------------------------------------
# Technique display names
# ---------------------------------------------------------------------------
TECHNIQUE_NAMES: dict[str, str] = {
    "T1046": "Network Service Discovery",
    "T1595.002": "Active Scanning: Vulnerability Scanning",
    "T1083": "File and Directory Discovery",
    "T1110.001": "Brute Force: Password Guessing",
    "T1190": "Exploit Public-Facing Application",
    "T1588.005": "Obtain Capabilities: Exploits",
    "T1203": "Exploitation for Client Execution",
    "T1003": "OS Credential Dumping",
    "T1068": "Exploitation for Privilege Escalation",
    "T1021": "Remote Services",
    "T1041": "Exfiltration Over C2 Channel",
}

# ---------------------------------------------------------------------------
# TECHNIQUE_MAP: (tool_id, action) → list of ATT&CK technique IDs
#
# Keys are ``(tool_id, action)`` tuples.  ``action`` is a short canonical
# verb describing what the tool does in the given invocation (e.g. "scan",
# "brute_force").  A wildcard action ``"*"`` matches any action for the
# tool when no more-specific entry exists.
# ---------------------------------------------------------------------------
TECHNIQUE_MAP: dict[tuple[str, str], list[str]] = {
    # nmap scanning → T1046 (Network Service Discovery)
    ("nmap", "*"): ["T1046"],
    ("nmap", "scan"): ["T1046"],
    # nuclei scanning → T1595.002 (Active Scanning: Vulnerability Scanning)
    ("nuclei", "*"): ["T1595.002"],
    ("nuclei", "scan"): ["T1595.002"],
    # gobuster / ffuf → T1083 (File and Directory Discovery)
    ("gobuster", "*"): ["T1083"],
    ("gobuster", "dir"): ["T1083"],
    ("ffuf", "*"): ["T1083"],
    ("ffuf", "fuzz"): ["T1083"],
    # hydra → T1110.001 (Brute Force: Password Guessing)
    ("hydra", "*"): ["T1110.001"],
    ("hydra", "brute_force"): ["T1110.001"],
    # sqlmap → T1190 (Exploit Public-Facing Application)
    ("sqlmap", "*"): ["T1190"],
    ("sqlmap", "exploit"): ["T1190"],
    # searchsploit → T1588.005 (Obtain Capabilities: Exploits)
    ("searchsploit", "*"): ["T1588.005"],
    ("searchsploit", "search"): ["T1588.005"],
    # metasploit → T1203 (Exploitation for Client Execution)
    ("metasploit", "*"): ["T1203"],
    ("metasploit", "exploit"): ["T1203"],
    # nikto → T1595.002
    ("nikto", "*"): ["T1595.002"],
    ("nikto", "scan"): ["T1595.002"],
    # wpscan → T1595.002
    ("wpscan", "*"): ["T1595.002"],
    ("wpscan", "scan"): ["T1595.002"],
    # credential dumping → T1003
    ("credential_dumping", "*"): ["T1003"],
    ("mimikatz", "*"): ["T1003"],
    # privilege escalation → T1068
    ("privilege_escalation", "*"): ["T1068"],
    ("linpeas", "*"): ["T1068"],
    # lateral movement → T1021
    ("lateral_movement", "*"): ["T1021"],
    ("psexec", "*"): ["T1021"],
    # data exfiltration → T1041
    ("data_exfiltration", "*"): ["T1041"],
    ("exfiltration", "*"): ["T1041"],
}


def _resolve_techniques(tool_id: str, action: str) -> list[str]:
    """Return ATT&CK technique IDs for a tool/action pair.

    Tries the specific ``(tool_id, action)`` key first, then falls back to
    ``(tool_id, "*")``.  Returns an empty list when no mapping exists.
    """
    tool = tool_id.lower().strip()
    act = action.lower().strip() if action else "*"
    return TECHNIQUE_MAP.get((tool, act)) or TECHNIQUE_MAP.get((tool, "*")) or []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def tag_finding_with_attack(finding: dict[str, Any]) -> dict[str, Any]:
    """Add ``mitre_techniques`` field to a finding dict.

    Looks at ``tool`` / ``tool_id`` and ``action`` keys in *finding* to
    determine matching ATT&CK technique IDs.  The result is a **copy** of
    the original dict with the added field so the caller's data is not
    mutated.

    Returns:
        A new dict with ``mitre_techniques`` — a list of dicts, each
        containing ``id`` and ``name`` of the matched technique.
    """
    tool_id = finding.get("tool_id") or finding.get("tool") or finding.get("source") or ""
    action = finding.get("action") or finding.get("type") or "*"

    technique_ids = _resolve_techniques(tool_id, action)

    techniques = [{"id": tid, "name": TECHNIQUE_NAMES.get(tid, tid)} for tid in technique_ids]

    return {**finding, "mitre_techniques": techniques}


def get_attack_summary(findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a tactic-level coverage summary for the given findings.

    Returns:
        A dict with:
        - ``tactics``: mapping of tactic ID → count of associated findings
        - ``tactic_names``: mapping of tactic ID → display name
        - ``total_techniques``: number of distinct techniques observed
        - ``total_findings_mapped``: number of findings that had at least
          one ATT&CK mapping
    """
    tactic_counts: dict[str, int] = {}
    total_mapped = 0
    technique_set: set[str] = set()

    for finding in findings:
        tagged = tag_finding_with_attack(finding)
        techniques = tagged.get("mitre_techniques", [])
        if techniques:
            total_mapped += 1
        for tech in techniques:
            tid = tech["id"]
            technique_set.add(tid)
            for tactic_id in TECHNIQUE_TACTICS.get(tid, []):
                tactic_counts[tactic_id] = tactic_counts.get(tactic_id, 0) + 1

    return {
        "tactics": tactic_counts,
        "tactic_names": {tid: TACTIC_NAMES.get(tid, tid) for tid in tactic_counts},
        "total_techniques": len(technique_set),
        "total_findings_mapped": total_mapped,
    }
