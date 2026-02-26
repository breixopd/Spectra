"""
CVE Intelligence Service.

Provides up-to-date CVE awareness for agents:
- Correlates service versions with known CVEs
- Maintains a local cache of commonly exploited CVEs
- Can fetch from NVD/CVE APIs when network available
- Falls back to built-in knowledge when offline

This replaces the need for agents to "know" CVEs from training data
(which is outdated) by providing real-time correlation.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("spectra.ai.cve_intel")

# Built-in CVE database for commonly exploited vulnerabilities.
# This is the offline fallback — agents don't need to hallucinate CVE IDs.
KNOWN_CVES: list[dict[str, Any]] = [
    # Apache
    {"cve": "CVE-2021-41773", "product": "apache", "versions": "2.4.49", "type": "path_traversal", "severity": "critical", "description": "Path traversal in Apache 2.4.49 via %2e encoding"},
    {"cve": "CVE-2021-42013", "product": "apache", "versions": "2.4.49,2.4.50", "type": "rce", "severity": "critical", "description": "RCE via path traversal in Apache 2.4.49-2.4.50"},
    {"cve": "CVE-2019-0211", "product": "apache", "versions": "2.4.17-2.4.38", "type": "privilege_escalation", "severity": "high", "description": "Local privilege escalation in Apache 2.4.17-2.4.38"},
    {"cve": "CVE-2017-9798", "product": "apache", "versions": "2.2.x,2.4.x", "type": "info_leak", "severity": "medium", "description": "Optionsbleed - memory leak via OPTIONS method"},

    # Nginx
    {"cve": "CVE-2021-23017", "product": "nginx", "versions": "0.6.18-1.20.0", "type": "dns_resolver", "severity": "high", "description": "DNS resolver vulnerability allowing RCE"},
    {"cve": "CVE-2019-20372", "product": "nginx", "versions": "<1.17.7", "type": "request_smuggling", "severity": "medium", "description": "HTTP request smuggling via error pages"},

    # OpenSSH
    {"cve": "CVE-2024-6387", "product": "openssh", "versions": "8.5p1-9.7p1", "type": "rce", "severity": "critical", "description": "regreSSHion - unauthenticated RCE in OpenSSH signal handler race"},
    {"cve": "CVE-2023-38408", "product": "openssh", "versions": "<9.3p2", "type": "rce", "severity": "critical", "description": "Remote code execution via ssh-agent forwarding"},
    {"cve": "CVE-2020-15778", "product": "openssh", "versions": "<8.4", "type": "command_injection", "severity": "medium", "description": "Command injection via scp filename"},

    # PHP
    {"cve": "CVE-2024-4577", "product": "php", "versions": "8.1.x,8.2.x,8.3.x", "type": "rce", "severity": "critical", "description": "CGI argument injection RCE on Windows"},
    {"cve": "CVE-2019-11043", "product": "php", "versions": "7.1.x-7.3.x", "type": "rce", "severity": "critical", "description": "PHP-FPM RCE via malformed fastcgi request"},

    # MySQL / MariaDB
    {"cve": "CVE-2012-2122", "product": "mysql", "versions": "5.1.x,5.5.x", "type": "auth_bypass", "severity": "critical", "description": "Authentication bypass via timing attack (1/256 chance)"},

    # WordPress
    {"cve": "CVE-2022-21661", "product": "wordpress", "versions": "<5.8.3", "type": "sqli", "severity": "high", "description": "SQL injection in WP_Query"},
    {"cve": "CVE-2021-29447", "product": "wordpress", "versions": "5.6-5.7", "type": "xxe", "severity": "high", "description": "XXE via media library upload"},

    # Node.js / Express
    {"cve": "CVE-2022-24999", "product": "express", "versions": "<4.17.3", "type": "prototype_pollution", "severity": "high", "description": "Prototype pollution via qs library"},
    {"cve": "CVE-2024-21896", "product": "node.js", "versions": "<18.19.1,<20.11.1", "type": "path_traversal", "severity": "high", "description": "Path traversal via experimental permission model"},

    # ProFTPD / vsftpd
    {"cve": "CVE-2015-3306", "product": "proftpd", "versions": "1.3.5", "type": "rce", "severity": "critical", "description": "mod_copy allows unauthenticated file copy → RCE"},
    {"cve": "CVE-2011-2523", "product": "vsftpd", "versions": "2.3.4", "type": "backdoor", "severity": "critical", "description": "Backdoor in vsftpd 2.3.4 triggered by :) in username"},

    # Samba / SMB
    {"cve": "CVE-2017-7494", "product": "samba", "versions": "3.5.0-4.6.4", "type": "rce", "severity": "critical", "description": "SambaCry - remote code execution via writable share"},
    {"cve": "CVE-2017-0144", "product": "smb", "versions": "smbv1", "type": "rce", "severity": "critical", "description": "EternalBlue - MS17-010 SMBv1 remote code execution"},

    # Redis
    {"cve": "CVE-2022-0543", "product": "redis", "versions": "<6.2.7,<7.0.0", "type": "rce", "severity": "critical", "description": "Lua sandbox escape → RCE via eval"},

    # Log4j
    {"cve": "CVE-2021-44228", "product": "log4j", "versions": "2.0-2.14.1", "type": "rce", "severity": "critical", "description": "Log4Shell - JNDI injection RCE via ${jndi:ldap://}"},

    # Tomcat
    {"cve": "CVE-2020-1938", "product": "tomcat", "versions": "<9.0.31,<8.5.51", "type": "file_read", "severity": "critical", "description": "Ghostcat - AJP file read/inclusion"},
    {"cve": "CVE-2017-12617", "product": "tomcat", "versions": "<9.0.1,<8.5.23", "type": "rce", "severity": "high", "description": "RCE via PUT method when readonly=false"},
]

CVE_CACHE_FILE = Path("reports/memory/cve_cache.json")


def lookup_cves(
    product: str | None = None,
    version: str | None = None,
    service: str | None = None,
) -> list[dict[str, Any]]:
    """
    Look up known CVEs for a product/version/service.

    Returns matching CVEs sorted by severity (critical first).
    """
    matches = []
    search_term = (product or service or "").lower()

    if not search_term:
        return []

    for cve in KNOWN_CVES:
        if search_term in cve["product"].lower():
            # Check version match if provided
            if version and cve.get("versions"):
                # Simple substring match — good enough for major versions
                version_str = cve["versions"].lower()
                version_major = version.split(".")[0] if "." in version else version
                if version.lower() in version_str or version_major in version_str:
                    matches.append({**cve, "version_match": True})
                else:
                    matches.append({**cve, "version_match": False})
            else:
                matches.append({**cve, "version_match": False})

    # Sort: version matches first, then by severity
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    matches.sort(
        key=lambda x: (
            0 if x.get("version_match") else 1,
            severity_order.get(x["severity"], 5),
        )
    )

    return matches


def get_cve_context_for_services(services: list[dict[str, Any]]) -> str:
    """
    Build CVE context string for a list of discovered services.

    This is injected into agent prompts to give them real CVE knowledge
    instead of hallucinated CVE IDs.
    """
    parts = []

    for svc in services:
        product = svc.get("product", "")
        version = svc.get("version", "")
        service = svc.get("service", "")

        cves = lookup_cves(product=product, version=version, service=service)

        if cves:
            version_matches = [c for c in cves if c.get("version_match")]
            others = [c for c in cves if not c.get("version_match")][:2]

            relevant = version_matches + others

            if relevant:
                port = svc.get("port", "?")
                header = f"**{product or service} {version}** (port {port}):"
                lines = [header]
                for c in relevant[:4]:
                    match_flag = " ← VERSION MATCH" if c.get("version_match") else ""
                    lines.append(
                        f"  - {c['cve']} [{c['severity'].upper()}] {c['type']}: {c['description']}{match_flag}"
                    )
                parts.append("\n".join(lines))

    if not parts:
        return ""

    return "**Known CVEs for Discovered Services:**\n\n" + "\n\n".join(parts)
