"""Built-in methodology checklists for manual pentesting."""

import logging
from typing import Any

logger = logging.getLogger(__name__)

BUILTIN_CHECKLISTS: dict[str, dict[str, Any]] = {
    "owasp_top10_2021": {
        "name": "OWASP Top 10 (2021)",
        "description": "Web application security testing checklist",
        "categories": [
            {
                "name": "A01: Broken Access Control",
                "items": [
                    {"id": "a01-01", "text": "Test IDOR: Access objects by modifying IDs", "tools": ["burp", "ffuf"]},
                    {"id": "a01-02", "text": "Test privilege escalation: Access admin functions as regular user"},
                    {"id": "a01-03", "text": "Test missing function level access control"},
                    {"id": "a01-04", "text": "Test CORS misconfigurations"},
                    {"id": "a01-05", "text": "Test directory traversal"},
                    {"id": "a01-06", "text": "Test forced browsing to authenticated pages"},
                ],
            },
            {
                "name": "A02: Cryptographic Failures",
                "items": [
                    {"id": "a02-01", "text": "Check TLS configuration (testssl)", "tools": ["testssl"]},
                    {"id": "a02-02", "text": "Check for sensitive data in transit (HTTP vs HTTPS)"},
                    {"id": "a02-03", "text": "Check password storage (hashing algorithm)"},
                    {"id": "a02-04", "text": "Check for hardcoded credentials"},
                ],
            },
            {
                "name": "A03: Injection",
                "items": [
                    {"id": "a03-01", "text": "Test SQL injection (manual + sqlmap)", "tools": ["sqlmap"]},
                    {"id": "a03-02", "text": "Test XSS (reflected, stored, DOM)"},
                    {"id": "a03-03", "text": "Test command injection"},
                    {"id": "a03-04", "text": "Test LDAP injection"},
                    {"id": "a03-05", "text": "Test template injection (SSTI)"},
                    {"id": "a03-06", "text": "Test XXE injection"},
                ],
            },
            {
                "name": "A04: Insecure Design",
                "items": [
                    {"id": "a04-01", "text": "Test business logic flaws"},
                    {"id": "a04-02", "text": "Test rate limiting on sensitive actions"},
                    {"id": "a04-03", "text": "Test for missing anti-automation"},
                ],
            },
            {
                "name": "A05: Security Misconfiguration",
                "items": [
                    {"id": "a05-01", "text": "Check default credentials", "tools": ["hydra"]},
                    {"id": "a05-02", "text": "Check unnecessary services/features enabled"},
                    {"id": "a05-03", "text": "Check security headers"},
                    {"id": "a05-04", "text": "Check error handling (stack traces exposed)"},
                    {"id": "a05-05", "text": "Check directory listing enabled"},
                ],
            },
            {
                "name": "A06: Vulnerable Components",
                "items": [
                    {"id": "a06-01", "text": "Identify component versions (whatweb, wappalyzer)", "tools": ["whatweb"]},
                    {"id": "a06-02", "text": "Check for known CVEs (nuclei, searchsploit)", "tools": ["nuclei", "searchsploit"]},
                ],
            },
            {
                "name": "A07: Auth Failures",
                "items": [
                    {"id": "a07-01", "text": "Test brute force protection"},
                    {"id": "a07-02", "text": "Test default/weak passwords", "tools": ["hydra"]},
                    {"id": "a07-03", "text": "Test session fixation"},
                    {"id": "a07-04", "text": "Test session timeout/invalidation"},
                    {"id": "a07-05", "text": "Test password reset flow"},
                    {"id": "a07-06", "text": "Test MFA bypass"},
                ],
            },
            {
                "name": "A08: Software & Data Integrity",
                "items": [
                    {"id": "a08-01", "text": "Check for insecure deserialization"},
                    {"id": "a08-02", "text": "Check CI/CD pipeline security"},
                ],
            },
            {
                "name": "A09: Logging & Monitoring",
                "items": [
                    {"id": "a09-01", "text": "Check if login failures are logged"},
                    {"id": "a09-02", "text": "Check if security events are monitored"},
                ],
            },
            {
                "name": "A10: SSRF",
                "items": [
                    {"id": "a10-01", "text": "Test SSRF via URL parameters"},
                    {"id": "a10-02", "text": "Test SSRF via file upload/import"},
                    {"id": "a10-03", "text": "Test SSRF via webhook/callback URLs"},
                ],
            },
        ],
    },
    "network_pentest": {
        "name": "Network Penetration Test",
        "description": "Infrastructure/network security assessment checklist",
        "categories": [
            {
                "name": "Reconnaissance",
                "items": [
                    {"id": "net-01", "text": "Port scan all targets (TCP)", "tools": ["nmap", "naabu"]},
                    {"id": "net-02", "text": "Port scan all targets (UDP top 100)", "tools": ["nmap"]},
                    {"id": "net-03", "text": "Service version detection", "tools": ["nmap"]},
                    {"id": "net-04", "text": "OS fingerprinting", "tools": ["nmap"]},
                    {"id": "net-05", "text": "DNS enumeration", "tools": ["subfinder", "amass"]},
                ],
            },
            {
                "name": "Enumeration",
                "items": [
                    {"id": "net-06", "text": "SMB enumeration (shares, users)", "tools": ["enum4linux", "crackmapexec"]},
                    {"id": "net-07", "text": "SNMP enumeration"},
                    {"id": "net-08", "text": "LDAP enumeration"},
                    {"id": "net-09", "text": "NFS enumeration (showmount)"},
                    {"id": "net-10", "text": "Web service enumeration", "tools": ["whatweb", "nikto"]},
                ],
            },
            {
                "name": "Vulnerability Assessment",
                "items": [
                    {"id": "net-11", "text": "Run vulnerability scanner", "tools": ["nuclei"]},
                    {"id": "net-12", "text": "Check for default credentials", "tools": ["hydra"]},
                    {"id": "net-13", "text": "Check for known CVEs"},
                    {"id": "net-14", "text": "SSL/TLS assessment", "tools": ["testssl"]},
                ],
            },
            {
                "name": "Exploitation",
                "items": [
                    {"id": "net-15", "text": "Attempt exploitation of critical vulns", "tools": ["metasploit"]},
                    {"id": "net-16", "text": "Password spraying", "tools": ["hydra", "kerbrute"]},
                    {"id": "net-17", "text": "Exploit verification and documentation"},
                ],
            },
            {
                "name": "Post-Exploitation",
                "items": [
                    {"id": "net-18", "text": "Privilege escalation", "tools": ["linpeas", "winpeas"]},
                    {"id": "net-19", "text": "Lateral movement"},
                    {"id": "net-20", "text": "Data exfiltration (proof of concept)"},
                    {"id": "net-21", "text": "Persistence mechanisms"},
                    {"id": "net-22", "text": "Clean up artifacts"},
                ],
            },
        ],
    },
    "api_security": {
        "name": "API Security Testing",
        "description": "REST/GraphQL API security assessment",
        "categories": [
            {
                "name": "Reconnaissance",
                "items": [
                    {"id": "api-01", "text": "Discover API endpoints (spider, docs)"},
                    {"id": "api-02", "text": "Identify API version and technology"},
                    {"id": "api-03", "text": "Map authentication mechanisms"},
                ],
            },
            {
                "name": "Authentication & Authorization",
                "items": [
                    {"id": "api-04", "text": "Test broken object level authorization (BOLA)"},
                    {"id": "api-05", "text": "Test broken authentication (weak tokens, no expiry)"},
                    {"id": "api-06", "text": "Test broken function level authorization"},
                    {"id": "api-07", "text": "Test mass assignment"},
                ],
            },
            {
                "name": "Input Validation",
                "items": [
                    {"id": "api-08", "text": "Test injection in all parameters"},
                    {"id": "api-09", "text": "Test excessive data exposure"},
                    {"id": "api-10", "text": "Test rate limiting"},
                    {"id": "api-11", "text": "Test improper inventory management"},
                ],
            },
        ],
    },
    "ad_pentest": {
        "name": "Active Directory Penetration Test",
        "description": "Active Directory assessment checklist",
        "categories": [
            {
                "name": "Initial Enumeration",
                "items": [
                    {"id": "ad-01", "text": "Enumerate domain controllers"},
                    {"id": "ad-02", "text": "Enumerate domain users", "tools": ["kerbrute", "enum4linux"]},
                    {"id": "ad-03", "text": "Enumerate domain groups and memberships"},
                    {"id": "ad-04", "text": "Enumerate GPOs and ACLs"},
                    {"id": "ad-05", "text": "Enumerate SPNs (Kerberoasting targets)", "tools": ["impacket"]},
                ],
            },
            {
                "name": "Authentication Attacks",
                "items": [
                    {"id": "ad-06", "text": "AS-REP Roasting (no preauth users)", "tools": ["impacket"]},
                    {"id": "ad-07", "text": "Kerberoasting (crack service tickets)", "tools": ["impacket"]},
                    {"id": "ad-08", "text": "Password spraying", "tools": ["kerbrute", "crackmapexec"]},
                    {"id": "ad-09", "text": "NTLM relay attacks", "tools": ["impacket"]},
                ],
            },
            {
                "name": "Privilege Escalation",
                "items": [
                    {"id": "ad-10", "text": "Check for local admin reuse", "tools": ["crackmapexec"]},
                    {"id": "ad-11", "text": "Check for unconstrained delegation"},
                    {"id": "ad-12", "text": "Check for constrained delegation abuse"},
                    {"id": "ad-13", "text": "DCSync attack", "tools": ["impacket"]},
                    {"id": "ad-14", "text": "Check for ZeroLogon (CVE-2020-1472)"},
                ],
            },
            {
                "name": "Lateral Movement",
                "items": [
                    {"id": "ad-15", "text": "Pass-the-Hash", "tools": ["impacket", "crackmapexec"]},
                    {"id": "ad-16", "text": "Pass-the-Ticket"},
                    {"id": "ad-17", "text": "WMI execution", "tools": ["impacket"]},
                    {"id": "ad-18", "text": "PSExec/SMBExec", "tools": ["impacket"]},
                ],
            },
            {
                "name": "Domain Dominance",
                "items": [
                    {"id": "ad-19", "text": "Golden Ticket attack"},
                    {"id": "ad-20", "text": "Silver Ticket attack"},
                    {"id": "ad-21", "text": "Skeleton Key attack"},
                    {"id": "ad-22", "text": "Extract NTDS.dit", "tools": ["impacket"]},
                ],
            },
        ],
    },
    "ptes": {
        "name": "PTES Standard",
        "description": "Penetration Testing Execution Standard phases",
        "categories": [
            {
                "name": "Pre-engagement",
                "items": [
                    {"id": "ptes-01", "text": "Define scope and rules of engagement"},
                    {"id": "ptes-02", "text": "Get written authorization"},
                    {"id": "ptes-03", "text": "Verify emergency contacts"},
                    {"id": "ptes-04", "text": "Confirm testing windows"},
                ],
            },
            {
                "name": "Intelligence Gathering",
                "items": [
                    {"id": "ptes-05", "text": "OSINT on target organization"},
                    {"id": "ptes-06", "text": "Technical footprinting"},
                    {"id": "ptes-07", "text": "Email harvesting"},
                    {"id": "ptes-08", "text": "Subdomain enumeration", "tools": ["subfinder", "amass"]},
                ],
            },
            {
                "name": "Threat Modeling",
                "items": [
                    {"id": "ptes-09", "text": "Identify high-value assets"},
                    {"id": "ptes-10", "text": "Map attack vectors"},
                    {"id": "ptes-11", "text": "Prioritize targets"},
                ],
            },
            {
                "name": "Vulnerability Analysis",
                "items": [
                    {"id": "ptes-12", "text": "Automated scanning", "tools": ["nuclei", "nmap"]},
                    {"id": "ptes-13", "text": "Manual testing of top findings"},
                    {"id": "ptes-14", "text": "False positive elimination"},
                ],
            },
            {
                "name": "Exploitation",
                "items": [
                    {"id": "ptes-15", "text": "Exploit verified vulnerabilities", "tools": ["metasploit"]},
                    {"id": "ptes-16", "text": "Document exploitation chain"},
                    {"id": "ptes-17", "text": "Capture evidence/screenshots"},
                ],
            },
            {
                "name": "Post-Exploitation",
                "items": [
                    {"id": "ptes-18", "text": "Privilege escalation", "tools": ["linpeas", "winpeas"]},
                    {"id": "ptes-19", "text": "Lateral movement"},
                    {"id": "ptes-20", "text": "Data pillaging (proof of concept)"},
                    {"id": "ptes-21", "text": "Persistence (document, don't leave)"},
                ],
            },
            {
                "name": "Reporting",
                "items": [
                    {"id": "ptes-22", "text": "Write executive summary"},
                    {"id": "ptes-23", "text": "Write technical findings"},
                    {"id": "ptes-24", "text": "Include remediation recommendations"},
                    {"id": "ptes-25", "text": "Peer review report"},
                ],
            },
        ],
    },
}


def list_checklists() -> list[dict[str, str]]:
    """Return summary list of all available checklists."""
    return [
        {"id": cid, "name": data["name"], "description": data["description"]}
        for cid, data in BUILTIN_CHECKLISTS.items()
    ]


def get_checklist(checklist_id: str) -> dict[str, Any] | None:
    """Return a full checklist by ID, or None if not found."""
    data = BUILTIN_CHECKLISTS.get(checklist_id)
    if data is None:
        return None
    return {"id": checklist_id, **data}
