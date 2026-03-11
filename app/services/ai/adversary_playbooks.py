"""
Adversary Simulation Playbooks.

Pre-built attack patterns that mimic specific threat actors' TTPs.
Each playbook defines an ordered sequence of techniques following
known APT tradecraft.
"""

import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class PlaybookStep(BaseModel):
    name: str
    description: str
    tool: str | None = None
    tool_args: dict[str, Any] = Field(default_factory=dict)
    mitre_technique: str = ""
    phase: str = "discovery"
    success_criteria: str | None = None
    fallback: str | None = None  # next step name if this fails


class AdversaryPlaybook(BaseModel):
    id: str
    name: str
    threat_actor: str
    description: str
    difficulty: str = "medium"
    tags: list[str] = Field(default_factory=list)
    mitre_tactics: list[str] = Field(default_factory=list)
    steps: list[PlaybookStep] = Field(default_factory=list)


ADVERSARY_PLAYBOOKS: list[dict[str, Any]] = [
    {
        "id": "apt28-web",
        "name": "APT28 Web Exploitation",
        "threat_actor": "APT28 (Fancy Bear)",
        "description": "Simulates APT28's web application exploitation chain: reconnaissance, vulnerability discovery, exploitation, credential harvesting, and persistence.",
        "difficulty": "hard",
        "tags": ["apt", "web", "credential-harvest", "persistence"],
        "mitre_tactics": ["TA0043", "TA0001", "TA0006", "TA0003"],
        "steps": [
            {"name": "web_recon", "description": "Technology fingerprinting and service enumeration", "tool": "whatweb", "phase": "discovery", "mitre_technique": "T1592"},
            {"name": "vuln_scan", "description": "Targeted vulnerability scanning", "tool": "nuclei", "phase": "vulnerability", "mitre_technique": "T1595.002"},
            {"name": "dir_enum", "description": "Directory and file discovery for admin panels", "tool": "gobuster", "phase": "enumeration", "mitre_technique": "T1083"},
            {"name": "exploit_web", "description": "Exploit discovered web vulnerabilities", "tool": "sqlmap", "phase": "exploitation", "mitre_technique": "T1190", "success_criteria": "injection found"},
            {"name": "cred_harvest", "description": "Extract credentials from compromised database", "tool": "sqlmap", "tool_args": {"dump": True}, "phase": "exploitation", "mitre_technique": "T1555"},
            {"name": "persistence", "description": "Establish persistence via web shell or backdoor", "phase": "post_exploitation", "mitre_technique": "T1505.003"},
        ],
    },
    {
        "id": "fin7-pos",
        "name": "FIN7 Point-of-Sale Attack",
        "threat_actor": "FIN7 (Carbanak)",
        "description": "Simulates FIN7's attack pattern targeting web applications to gain initial access, then pivoting to internal systems.",
        "difficulty": "hard",
        "tags": ["apt", "financial", "web", "lateral-movement"],
        "mitre_tactics": ["TA0001", "TA0002", "TA0008", "TA0010"],
        "steps": [
            {"name": "port_scan", "description": "Full port scan with service detection", "tool": "nmap", "phase": "discovery", "mitre_technique": "T1046"},
            {"name": "web_vuln", "description": "Web vulnerability assessment", "tool": "nuclei", "phase": "vulnerability", "mitre_technique": "T1190"},
            {"name": "default_creds", "description": "Test default credentials on discovered services", "tool": "hydra", "phase": "exploitation", "mitre_technique": "T1078.001"},
            {"name": "exploit", "description": "Exploit most promising vulnerability", "phase": "exploitation", "mitre_technique": "T1190"},
            {"name": "internal_recon", "description": "Enumerate internal network from compromised host", "phase": "post_exploitation", "mitre_technique": "T1018"},
            {"name": "data_staging", "description": "Identify and stage sensitive data", "phase": "post_exploitation", "mitre_technique": "T1074"},
        ],
    },
    {
        "id": "generic-network",
        "name": "Network Infrastructure Assessment",
        "threat_actor": "Generic Pentester",
        "description": "Standard network penetration test pattern following PTES methodology.",
        "difficulty": "medium",
        "tags": ["network", "standard", "ptes"],
        "mitre_tactics": ["TA0043", "TA0001", "TA0002", "TA0004"],
        "steps": [
            {"name": "discovery", "description": "Port scanning and service enumeration", "tool": "nmap", "phase": "discovery", "mitre_technique": "T1046"},
            {"name": "vuln_scan", "description": "Vulnerability scanning with multiple tools", "tool": "nuclei", "phase": "vulnerability", "mitre_technique": "T1595.002"},
            {"name": "web_enum", "description": "Web directory enumeration", "tool": "gobuster", "phase": "enumeration", "mitre_technique": "T1083"},
            {"name": "cve_search", "description": "Search for public exploits", "tool": "searchsploit", "phase": "vulnerability", "mitre_technique": "T1588.005"},
            {"name": "exploitation", "description": "Attempt exploitation of found vulns", "phase": "exploitation", "mitre_technique": "T1190"},
            {"name": "reporting", "description": "Generate assessment report", "phase": "reporting"},
        ],
    },
    {
        "id": "insider-threat",
        "name": "Insider Threat Simulation",
        "threat_actor": "Malicious Insider",
        "description": "Simulates an insider with network access attempting to escalate privileges and exfiltrate data.",
        "difficulty": "medium",
        "tags": ["insider", "privilege-escalation", "data-exfil"],
        "mitre_tactics": ["TA0004", "TA0006", "TA0009", "TA0010"],
        "steps": [
            {"name": "internal_scan", "description": "Scan internal network for services", "tool": "nmap", "phase": "discovery", "mitre_technique": "T1046"},
            {"name": "service_enum", "description": "Enumerate accessible services", "tool": "nuclei", "phase": "enumeration", "mitre_technique": "T1046"},
            {"name": "default_creds", "description": "Test default and weak credentials", "tool": "hydra", "phase": "exploitation", "mitre_technique": "T1110.001"},
            {"name": "priv_esc", "description": "Attempt privilege escalation", "phase": "post_exploitation", "mitre_technique": "T1068"},
            {"name": "data_discovery", "description": "Search for sensitive data", "phase": "post_exploitation", "mitre_technique": "T1083"},
        ],
    },
]


def get_adversary_playbook(playbook_id: str) -> AdversaryPlaybook | None:
    """Get a specific adversary playbook by ID."""
    for pb_data in ADVERSARY_PLAYBOOKS:
        if pb_data["id"] == playbook_id:
            steps = [PlaybookStep(**s) for s in pb_data.get("steps", [])]
            return AdversaryPlaybook(steps=steps, **{k: v for k, v in pb_data.items() if k != "steps"})
    return None


def list_adversary_playbooks() -> list[dict[str, Any]]:
    """List all available adversary playbooks (without full steps)."""
    return [
        {
            "id": pb["id"],
            "name": pb["name"],
            "threat_actor": pb["threat_actor"],
            "description": pb["description"],
            "difficulty": pb["difficulty"],
            "tags": pb["tags"],
            "step_count": len(pb["steps"]),
        }
        for pb in ADVERSARY_PLAYBOOKS
    ]
