"""
CVE Intelligence Service.

Provides up-to-date CVE awareness for agents:
1. Live fetching from NVD API 2.0 (free, no auth required)
2. Local JSON cache with configurable TTL (default 24h)
3. Built-in fallback database for API downtime resilience
4. Version-to-CVE correlation for discovered services

Agents get real CVE data instead of hallucinating IDs.
"""

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.services.exploit_db import get_exploit_db
from spectra_common.constants import CVE_CACHE_TTL, EXTERNAL_HTTP_TIMEOUT, NVD_API_BASE_URL, NVD_RATE_LIMIT_DELAY

logger = logging.getLogger(__name__)


# =============================================================================
# Metasploit module database — now provided by ExploitDatabase service
# (see app/services/ai/exploit_db.py).
# =============================================================================


# =============================================================================
# CVE Knowledge Base — loaded from downloaded JSON, not hardcoded
# =============================================================================

_cve_knowledge_base: list[dict[str, Any]] | None = None


def _load_cve_knowledge_base() -> list[dict[str, Any]]:
    """Return cached CVE knowledge base (sync, non-blocking).

    Returns whatever is already loaded in memory.  Use
    ``_load_cve_knowledge_base_async()`` to populate from the database.
    """
    if _cve_knowledge_base is not None:
        return _cve_knowledge_base
    return []


async def _load_cve_knowledge_base_async() -> list[dict[str, Any]]:
    """Load CVE knowledge base from PostgreSQL cache (async version)."""
    global _cve_knowledge_base
    if _cve_knowledge_base is not None:
        return _cve_knowledge_base

    db = get_exploit_db()
    try:
        data = await db._cache_get("cve_knowledge_base")
    except Exception as exc:
        logger.warning("Failed to load CVE knowledge base: %s", exc)
        data = None

    _cve_knowledge_base = data if isinstance(data, list) else []
    if _cve_knowledge_base:
        logger.info("Loaded CVE knowledge base: %d entries", len(_cve_knowledge_base))
    return _cve_knowledge_base


async def reload_cve_knowledge_base() -> int:
    """Force reload of the CVE knowledge base from DB. Returns entry count."""
    global _cve_knowledge_base
    _cve_knowledge_base = None
    loaded = await _load_cve_knowledge_base_async()
    return len(loaded)


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
    cached = await _load_cache(keyword)
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

        async with httpx.AsyncClient(timeout=EXTERNAL_HTTP_TIMEOUT) as client:
            _last_nvd_request = time.time()
            response = await client.get(NVD_API_BASE_URL, params=params)

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
                        parts = cpe.split(":") if cpe else []
                        if len(parts) > 4:
                            products.append(parts[4])

            results.append(
                {
                    "cve": cve_id,
                    "description": desc[:300],
                    "severity": severity,
                    "cvss_score": cvss_score,
                    "products": products,
                    "product": keyword.lower(),
                    "type": _infer_vuln_type(desc),
                    "source": "nvd_api",
                    "fetched_at": datetime.now(UTC).isoformat(),
                }
            )

        # Cache results
        await _save_cache(keyword, results)

        logger.info("Fetched %d CVEs from NVD for '%s'", len(results), keyword)
        return results

    except httpx.TimeoutException:
        logger.warning("NVD API timeout for '%s'", keyword)
        return []
    except (OSError, RuntimeError, ConnectionError, TimeoutError) as e:
        logger.warning("NVD API error for '%s': %s", keyword, e)
        return []


# Pre-computed mapping for vulnerability inference
TYPE_KEYWORDS = {
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


def _infer_vuln_type(description: str) -> str:
    """Infer vulnerability type from description text."""
    desc_lower = description.lower()
    # Performance Optimization: Avoid creating the dictionary and using any() closure
    # inside a frequently called function.
    for vuln_type, keywords in TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in desc_lower:
                return vuln_type
    return "unknown"


# =============================================================================
# Local Cache
# =============================================================================


async def _load_cache(keyword: str) -> list[dict[str, Any]] | None:
    """Load cached CVE results if still fresh."""
    db = get_exploit_db()
    cache_key = f"cve_cache:{keyword.lower().replace(' ', '_').replace('/', '_')[:50]}"
    try:
        data = await db._cache_get(cache_key)
    except Exception:
        logger.debug("CVE cache read failed for %s", cache_key, exc_info=True)
        return None

    if data is None:
        return None
    cached_at = data.get("cached_at", 0)
    if time.time() - cached_at > CVE_CACHE_TTL:
        return None
    return data.get("results", [])


async def _save_cache(keyword: str, results: list[dict[str, Any]]) -> None:
    """Save CVE results to cache."""
    db = get_exploit_db()
    cache_key = f"cve_cache:{keyword.lower().replace(' ', '_').replace('/', '_')[:50]}"
    payload = {
        "keyword": keyword,
        "cached_at": time.time(),
        "results": results,
    }
    try:
        await db._cache_set(cache_key, payload, CVE_CACHE_TTL)
    except Exception as e:
        logger.debug("Failed to cache CVEs: %s", e)


# =============================================================================
# Exploit enrichment helpers
# =============================================================================


def get_metasploit_modules(cve_id: str) -> list[dict]:
    """Get exploit modules for a CVE ID from all sources."""
    from app.services.exploit_db import get_exploit_db

    db = get_exploit_db()
    return db.lookup(cve_id)


def enrich_cve_with_exploits(cve: dict) -> dict:
    """Enrich a CVE result with exploit availability from all sources."""
    cve_id = cve.get("cve", "")
    modules = get_metasploit_modules(cve_id)

    from app.services.exploit_db import get_exploit_db

    db = get_exploit_db()

    cve["metasploit_modules"] = [m for m in modules if m.get("source") == "metasploit"]
    cve["exploitdb_refs"] = [m for m in modules if m.get("source") == "exploitdb"]
    cve["exploit_available"] = len(modules) > 0
    cve["exploit_count"] = len(modules)
    cve["kev_exploited"] = db.is_kev(cve_id)
    return cve


async def search_exploitdb(query: str) -> list[dict]:
    """Search ExploitDB from local index."""
    from app.services.exploit_db import get_exploit_db

    db = get_exploit_db()
    return db.search_exploitdb(query)


# =============================================================================
# Unified Lookup (builtin + live API)
# =============================================================================


# Pre-computed severity sorting weights
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def lookup_cves(
    product: str | None = None,
    version: str | None = None,
    service: str | None = None,
) -> list[dict[str, Any]]:
    """
    Look up known CVEs from the built-in database.

    For real-time results, use lookup_cves_live() which also queries NVD API.
    """
    search_term = (product or service or "").lower()
    if not search_term:
        return []

    version_lower = version.lower() if version else None
    version_major = version_lower.split(".")[0] if version_lower and "." in version_lower else version_lower

    matches = []
    for cve in _load_cve_knowledge_base():
        # Performance Optimization: Avoid repeated .lower() calls on builtin dict elements
        # which are already lowercased and static. Also avoid dict expansion overhead ({**cve}).
        if search_term in cve["product"]:
            version_match = False
            if version_lower and "versions" in cve:
                v_str = cve["versions"]
                if version_lower in v_str or (version_major and version_major in v_str):
                    version_match = True

            cve_copy = cve.copy()
            cve_copy["version_match"] = version_match
            cve_copy["source"] = "builtin"
            matches.append(cve_copy)

    if not matches:
        return []

    matches.sort(
        key=lambda x: (
            0 if x["version_match"] else 1,
            SEVERITY_ORDER.get(x["severity"], 5),
        )
    )

    return [enrich_cve_with_exploits(m) for m in matches]


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
    # Start with builtin results — ensure async loading first
    await _load_cve_knowledge_base_async()
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

    except (OSError, RuntimeError, ConnectionError, TimeoutError) as e:
        logger.debug("Live CVE fetch failed, using builtin only: %s", e)

    # Re-sort merged results
    builtin.sort(
        key=lambda x: (
            0 if x.get("version_match") else 1,
            SEVERITY_ORDER.get(x.get("severity", "medium"), 5),
        )
    )

    return [enrich_cve_with_exploits(c) for c in builtin]


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
                        f"  - {c['cve']} [{c['severity'].upper()}] {c['type']}: {c['description'][:120]}{match_flag}"
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

        cves = await lookup_cves_live(product=product, version=version, service=service_name)

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
