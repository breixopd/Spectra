"""Scan presets for one-click mission profiles."""

SCAN_PRESETS = {
    "quick_recon": {
        "name": "Quick Recon",
        "icon": "bolt",
        "description": "Fast port scan + basic vuln check (5 min)",
        "directive": "Quick reconnaissance scan. Run nmap for port discovery and nuclei with top templates only. Do not enumerate directories or attempt exploitation.",
        "stealth_mode": False,
        "estimated_minutes": 5,
    },
    "full_assessment": {
        "name": "Full Assessment",
        "icon": "shield",
        "description": "Complete PTES pentest - all phases (30+ min)",
        "directive": "Perform a comprehensive penetration test following PTES methodology. Discover all services, enumerate thoroughly, scan for vulnerabilities, attempt exploitation of confirmed vulns, and generate a detailed report.",
        "stealth_mode": False,
        "estimated_minutes": 30,
    },
    "web_only": {
        "name": "Web Application",
        "icon": "globe",
        "description": "Web-focused scan - OWASP Top 10 (15 min)",
        "directive": "Web application security assessment. Focus on web services only: directory enumeration, vulnerability scanning with nuclei web templates, SQL injection testing, and web server misconfiguration checks. Skip network-level attacks.",
        "stealth_mode": False,
        "estimated_minutes": 15,
    },
    "stealth": {
        "name": "Stealth Scan",
        "icon": "ghost",
        "description": "Low and slow - minimize detection (45+ min)",
        "directive": "Stealthy security assessment. Use slow timing, passive techniques first, minimize network noise. Avoid brute-force and aggressive scanning. Focus on passive recon and careful targeted probing.",
        "stealth_mode": True,
        "estimated_minutes": 45,
    },
    "exploit_focus": {
        "name": "Exploitation Focus",
        "icon": "crosshairs",
        "description": "Skip recon, focus on exploiting known vulns",
        "directive": "Exploitation-focused assessment. Perform minimal discovery then immediately attempt exploitation of any discovered services. Prioritize CVE-based exploits and default credential checks. Generate custom exploits if needed.",
        "stealth_mode": False,
        "estimated_minutes": 20,
    },
    "api_security": {
        "name": "API Security",
        "icon": "code",
        "description": "REST/GraphQL API assessment (15 min)",
        "directive": "API security assessment. Discover API endpoints, test for authentication bypass, injection flaws, IDOR vulnerabilities, and misconfigured CORS. Focus on the API attack surface.",
        "stealth_mode": False,
        "estimated_minutes": 15,
    },
}
