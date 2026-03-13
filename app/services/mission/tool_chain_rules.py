"""
Deterministic rules for automated tool chaining.
When a tool produces certain output patterns, automatically queue follow-up tools.
No LLM needed for these common patterns.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ChainRule:
    source_tool: str
    trigger_pattern: str  # regex to match in output
    next_tool: str
    next_args_template: dict[str, str]  # args for next tool, with {placeholders}
    description: str
    priority: int = 5  # 1=highest


# Placeholder names indexed by capture group position
_PLACEHOLDER_NAMES = (
    "port",
    "version",
    "path",
    "cve_id",
    "url",
    "user",
    "pass",
    "subdomain",
    "binary",
)

CHAIN_RULES: list[ChainRule] = [
    # Port scan -> Service enumeration
    ChainRule(
        "nmap",
        r"(\d+)/tcp\s+open\s+http",
        "whatweb",
        {"target": "{host}:{port}"},
        "Web service detected -> fingerprint",
        3,
    ),
    ChainRule(
        "nmap",
        r"(\d+)/tcp\s+open\s+http",
        "nikto",
        {"target": "{host}", "port": "{port}"},
        "Web service -> vuln scan",
        5,
    ),
    ChainRule(
        "nmap",
        r"(\d+)/tcp\s+open\s+http",
        "dirsearch",
        {"target": "http://{host}:{port}"},
        "Web service -> directory brute",
        6,
    ),
    # Port scan -> Protocol-specific tools
    ChainRule("nmap", r"445/tcp\s+open", "enum4linux", {"target": "{host}"}, "SMB detected -> enumerate", 3),
    ChainRule(
        "nmap",
        r"445/tcp\s+open",
        "crackmapexec",
        {"target": "{host}", "protocol": "smb"},
        "SMB -> CrackMapExec enum",
        5,
    ),
    ChainRule(
        "nmap",
        r"88/tcp\s+open",
        "kerbrute",
        {"target": "{host}", "mode": "userenum"},
        "Kerberos -> user enumeration",
        4,
    ),
    ChainRule("nmap", r"3306/tcp\s+open", "hydra", {"target": "{host}", "service": "mysql"}, "MySQL -> brute force", 7),
    ChainRule(
        "nmap", r"5432/tcp\s+open", "hydra", {"target": "{host}", "service": "postgres"}, "PostgreSQL -> brute force", 7
    ),
    ChainRule("nmap", r"21/tcp\s+open", "hydra", {"target": "{host}", "service": "ftp"}, "FTP -> brute force", 7),
    ChainRule("nmap", r"22/tcp\s+open", "hydra", {"target": "{host}", "service": "ssh"}, "SSH -> brute force", 8),
    # Web fingerprint -> CVE scan
    ChainRule(
        "whatweb",
        r"Apache[/ ](\d+\.\d+\.\d+)",
        "nuclei",
        {"target": "{host}", "tags": "apache,cve"},
        "Apache version -> CVE scan",
        3,
    ),
    ChainRule("whatweb", r"WordPress", "wpscan", {"target": "http://{host}"}, "WordPress detected -> WPScan", 2),
    ChainRule(
        "whatweb",
        r"nginx[/ ](\d+\.\d+)",
        "nuclei",
        {"target": "{host}", "tags": "nginx,cve"},
        "nginx version -> CVE scan",
        3,
    ),
    # Directory discovery -> deeper scan
    ChainRule(
        "dirsearch",
        r"200\s+\d+\S*\s+(/[\w/.-]+\.php)",
        "sqlmap",
        {"target": "http://{host}{path}"},
        "PHP endpoint -> SQLi test",
        5,
    ),
    ChainRule(
        "gobuster",
        r"Status: 200.*(/[\w/.-]+)",
        "nuclei",
        {"target": "http://{host}{path}"},
        "Found path -> vuln scan",
        6,
    ),
    ChainRule(
        "ffuf", r"Status: 200.*(/[\w/.-]+)", "nuclei", {"target": "http://{host}{path}"}, "Found path -> vuln scan", 6
    ),
    # Vulnerability scan -> exploitation
    ChainRule(
        "nuclei", r"\[critical\].*CVE-\d+-\d+", "searchsploit", {"query": "{cve_id}"}, "Critical CVE -> find exploit", 2
    ),
    ChainRule(
        "nuclei", r"\[high\].*sql.*injection", "sqlmap", {"target": "{url}"}, "SQLi vuln -> sqlmap exploitation", 3
    ),
    # Credential found -> pivot
    ChainRule(
        "hydra",
        r"login:\s+(\S+)\s+password:\s+(\S+)",
        "crackmapexec",
        {"target": "{host}", "username": "{user}", "password": "{pass}"},
        "Creds found -> lateral movement",
        2,
    ),
    # Enum4linux -> Kerberoasting
    ChainRule(
        "enum4linux",
        r"user:\[(\w+)\]",
        "kerbrute",
        {"target": "{host}", "mode": "passwordspray"},
        "Users found -> password spray",
        5,
    ),
    # Subfinder -> httpx
    ChainRule(
        "subfinder", r"([\w.-]+\.[\w]+)", "httpx", {"target": "{subdomain}"}, "Subdomain found -> probe alive", 3
    ),
    # Post-exploitation chains
    ChainRule(
        "linpeas",
        r"SUID.*(/usr/\S+)",
        "searchsploit",
        {"query": "{binary} privilege escalation"},
        "SUID binary -> find privesc",
        3,
    ),
]


def get_triggered_rules(source_tool: str, output: str, host: str) -> list[tuple[ChainRule, dict[str, str]]]:
    """Check output against chain rules and return triggered rules with resolved args."""
    triggered: list[tuple[ChainRule, dict[str, str]]] = []
    for rule in CHAIN_RULES:
        if rule.source_tool != source_tool:
            continue
        match = re.search(rule.trigger_pattern, output)
        if match:
            args: dict[str, str] = {}
            for k, v in rule.next_args_template.items():
                resolved = v.replace("{host}", host)
                for i, group in enumerate(match.groups()):
                    if group is not None:
                        placeholder = _PLACEHOLDER_NAMES[min(i, len(_PLACEHOLDER_NAMES) - 1)]
                        resolved = resolved.replace(f"{{{placeholder}}}", group)
                args[k] = resolved
            triggered.append((rule, args))
    triggered.sort(key=lambda x: x[0].priority)
    return triggered
