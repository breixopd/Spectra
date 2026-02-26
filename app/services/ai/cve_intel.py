"""
CVE Intelligence Service.

Provides up-to-date CVE awareness for agents:
1. Live fetching from NVD API 2.0 (free, no auth required)
2. Local JSON cache with configurable TTL (default 24h)
3. Built-in fallback database for offline/air-gapped operation
4. Version-to-CVE correlation for discovered services

Agents get real CVE data instead of hallucinating IDs.
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("spectra.ai.cve_intel")

# NVD API configuration
NVD_API_BASE = "https://services.nvd.nist.gov/rest/json/cves/2.0"
NVD_RATE_LIMIT_DELAY = 6.5  # seconds between requests (5 req / 30s limit)
CVE_CACHE_DIR = Path("reports/memory/cve_cache")
CVE_CACHE_TTL = 86400  # 24 hours


# =============================================================================
# Built-in CVE database (offline fallback)
# =============================================================================

BUILTIN_CVES: list[dict[str, Any]] = [
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
    # FTP
    {"cve": "CVE-2015-3306", "product": "proftpd", "versions": "1.3.5", "type": "rce", "severity": "critical", "description": "mod_copy allows unauthenticated file copy → RCE"},
    {"cve": "CVE-2011-2523", "product": "vsftpd", "versions": "2.3.4", "type": "backdoor", "severity": "critical", "description": "Backdoor in vsftpd 2.3.4 triggered by :) in username"},
    # SMB
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


# =============================================================================
# NVD API Live Fetching
# =============================================================================

# Track last request time for rate limiting
_last_nvd_request = 0.0


async def fetch_cves_from_nvd(
    keyword: str,
    max_results: int = 20,
) -> list[dict[str, Any]]:
    """
    Fetch CVEs from NVD API 2.0 by keyword search.

    Rate-limited to 5 requests per 30 seconds (NVD public limit).
    Results are cached locally for 24 hours.
    """
    global _last_nvd_request

    # Check cache first
    cached = _load_cache(keyword)
    if cached is not None:
        return cached

    # Rate limiting
    now = time.time()
    wait = NVD_RATE_LIMIT_DELAY - (now - _last_nvd_request)
    if wait > 0:
        await asyncio.sleep(wait)

    try:
        params = {
            "keywordSearch": keyword,
            "resultsPerPage": min(max_results, 50),
        }

        async with httpx.AsyncClient(timeout=15) as client:
            _last_nvd_request = time.time()
            response = await client.get(NVD_API_BASE, params=params)

            if response.status_code == 403:
                logger.warning("NVD API rate limited, using cached/builtin data")
                return []

            if response.status_code != 200:
                logger.warning("NVD API returned %d", response.status_code)
                return []

            data = response.json()

        # Parse NVD response
        results = []
        for vuln in data.get("vulnerabilities", []):
            cve_data = vuln.get("cve", {})
            cve_id = cve_data.get("id", "")

            # Get description
            descriptions = cve_data.get("descriptions", [])
            desc = next(
                (d["value"] for d in descriptions if d.get("lang") == "en"),
                "",
            )

            # Get CVSS severity
            metrics = cve_data.get("metrics", {})
            severity = "medium"
            cvss_score = 0.0
            for metric_key in ["cvssMetricV31", "cvssMetricV30", "cvssMetricV2"]:
                metric_list = metrics.get(metric_key, [])
                if metric_list:
                    cvss_data = metric_list[0].get("cvssData", {})
                    severity = cvss_data.get("baseSeverity", "MEDIUM").lower()
                    cvss_score = cvss_data.get("baseScore", 0.0)
                    break

            # Get affected products
            products = []
            for config in cve_data.get("configurations", []):
                for node in config.get("nodes", []):
                    for match in node.get("cpeMatch", []):
                        cpe = match.get("criteria", "")
                        if cpe:
                            parts = cpe.split(":")
                            if len(parts) > 4:
                                products.append(parts[4])

            results.append({
                "cve": cve_id,
                "description": desc[:300],
                "severity": severity,
                "cvss_score": cvss_score,
                "products": products,
                "product": keyword.lower(),
                "type": _infer_vuln_type(desc),
                "source": "nvd_api",
                "fetched_at": datetime.now().isoformat(),
            })

        # Cache results
        _save_cache(keyword, results)

        logger.info("Fetched %d CVEs from NVD for '%s'", len(results), keyword)
        return results

    except httpx.TimeoutException:
        logger.warning("NVD API timeout for '%s'", keyword)
        return []
    except Exception as e:
        logger.warning("NVD API error for '%s': %s", keyword, e)
        return []


def _infer_vuln_type(description: str) -> str:
    """Infer vulnerability type from description text."""
    desc_lower = description.lower()
    type_keywords = {
        "rce": ["remote code execution", "arbitrary code", "command execution"],
        "sqli": ["sql injection"],
        "xss": ["cross-site scripting", "xss"],
        "path_traversal": ["path traversal", "directory traversal"],
        "auth_bypass": ["authentication bypass", "auth bypass"],
        "privilege_escalation": ["privilege escalation", "privesc"],
        "info_leak": ["information disclosure", "information leak", "sensitive data"],
        "dos": ["denial of service", "crash", "resource exhaustion"],
        "ssrf": ["server-side request forgery", "ssrf"],
        "xxe": ["xml external entity", "xxe"],
    }
    for vuln_type, keywords in type_keywords.items():
        if any(kw in desc_lower for kw in keywords):
            return vuln_type
    return "unknown"


# =============================================================================
# Local Cache
# =============================================================================


def _cache_path(keyword: str) -> Path:
    """Get cache file path for a keyword."""
    safe_name = keyword.lower().replace(" ", "_").replace("/", "_")[:50]
    return CVE_CACHE_DIR / f"{safe_name}.json"


def _load_cache(keyword: str) -> list[dict[str, Any]] | None:
    """Load cached CVE results if still fresh."""
    path = _cache_path(keyword)
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text())
        cached_at = data.get("cached_at", 0)
        if time.time() - cached_at > CVE_CACHE_TTL:
            return None
        return data.get("results", [])
    except Exception:
        return None


def _save_cache(keyword: str, results: list[dict[str, Any]]) -> None:
    """Save CVE results to cache."""
    CVE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(keyword)
    try:
        path.write_text(json.dumps({
            "keyword": keyword,
            "cached_at": time.time(),
            "results": results,
        }, indent=2))
    except Exception as e:
        logger.debug("Failed to cache CVEs: %s", e)


# =============================================================================
# Unified Lookup (builtin + live API)
# =============================================================================


def lookup_cves(
    product: str | None = None,
    version: str | None = None,
    service: str | None = None,
) -> list[dict[str, Any]]:
    """
    Look up known CVEs from the built-in database.

    For real-time results, use lookup_cves_live() which also queries NVD API.
    """
    matches = []
    search_term = (product or service or "").lower()

    if not search_term:
        return []

    for cve in BUILTIN_CVES:
        if search_term in cve["product"].lower():
            if version and cve.get("versions"):
                version_str = cve["versions"].lower()
                version_major = version.split(".")[0] if "." in version else version
                if version.lower() in version_str or version_major in version_str:
                    matches.append({**cve, "version_match": True, "source": "builtin"})
                else:
                    matches.append({**cve, "version_match": False, "source": "builtin"})
            else:
                matches.append({**cve, "version_match": False, "source": "builtin"})

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    matches.sort(
        key=lambda x: (
            0 if x.get("version_match") else 1,
            severity_order.get(x["severity"], 5),
        )
    )

    return matches


async def lookup_cves_live(
    product: str | None = None,
    version: str | None = None,
    service: str | None = None,
) -> list[dict[str, Any]]:
    """
    Look up CVEs from both built-in database AND live NVD API.

    Merges results, deduplicates by CVE ID, and sorts by relevance.
    Falls back to builtin-only if NVD is unreachable.
    """
    # Start with builtin results
    builtin = lookup_cves(product=product, version=version, service=service)
    builtin_ids = {c["cve"] for c in builtin}

    # Try live NVD fetch
    search_term = product or service or ""
    if not search_term:
        return builtin

    # Add version to search for more specific results
    query = f"{search_term} {version}" if version else search_term

    try:
        live_results = await fetch_cves_from_nvd(query)

        # Merge: add live results that aren't already in builtin
        for cve in live_results:
            if cve["cve"] not in builtin_ids:
                # Check version match for live results
                version_match = False
                if version:
                    # Simple check: version appears in any product string
                    for p in cve.get("products", []):
                        if version.lower() in p.lower():
                            version_match = True
                            break

                cve["version_match"] = version_match
                builtin.append(cve)
                builtin_ids.add(cve["cve"])

    except Exception as e:
        logger.debug("Live CVE fetch failed, using builtin only: %s", e)

    # Re-sort merged results
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    builtin.sort(
        key=lambda x: (
            0 if x.get("version_match") else 1,
            severity_order.get(x.get("severity", "medium"), 5),
        )
    )

    return builtin


def get_cve_context_for_services(services: list[dict[str, Any]]) -> str:
    """
    Build CVE context string for a list of discovered services.

    Uses builtin database (fast, synchronous). For live data,
    use get_cve_context_for_services_live().
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
                        f"  - {c['cve']} [{c['severity'].upper()}] {c['type']}: "
                        f"{c['description'][:120]}{match_flag}"
                    )
                parts.append("\n".join(lines))

    if not parts:
        return ""

    return "**Known CVEs for Discovered Services:**\n\n" + "\n\n".join(parts)


async def get_cve_context_for_services_live(
    services: list[dict[str, Any]],
) -> str:
    """Build CVE context with live NVD data (async, may be slower)."""
    parts = []

    for svc in services:
        product = svc.get("product", "")
        version = svc.get("version", "")
        service_name = svc.get("service", "")

        if not product and not service_name:
            continue

        cves = await lookup_cves_live(
            product=product, version=version, service=service_name
        )

        if cves:
            relevant = cves[:5]
            port = svc.get("port", "?")
            header = f"**{product or service_name} {version}** (port {port}):"
            lines = [header]
            for c in relevant:
                source = f" [{c.get('source', 'unknown')}]" if c.get("source") == "nvd_api" else ""
                match_flag = " ← VERSION MATCH" if c.get("version_match") else ""
                lines.append(
                    f"  - {c['cve']} [{c.get('severity', 'medium').upper()}] "
                    f"{c.get('type', 'unknown')}: {c['description'][:120]}"
                    f"{match_flag}{source}"
                )
            parts.append("\n".join(lines))

    if not parts:
        return ""

    return "**Known CVEs for Discovered Services:**\n\n" + "\n\n".join(parts)
