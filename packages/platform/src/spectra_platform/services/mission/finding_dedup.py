"""Finding deduplication logic for missions.

Standalone functions for detecting exact and fuzzy duplicate findings,
extracted from the Mission class for reuse and testability.
"""

from __future__ import annotations

import asyncio
import functools
from typing import Any

# CVE relatedness groups — CVEs often published together for the same root cause
RELATED_CVE_GROUPS: list[set[str]] = [
    {"CVE-2021-41773", "CVE-2021-42013"},  # Apache path traversal variants
    {"CVE-2021-44228", "CVE-2021-45046", "CVE-2021-45105"},  # Log4Shell family
    {"CVE-2023-44487", "CVE-2024-27316"},  # HTTP/2 rapid reset variants
]


def are_related_cves(cve_a: str | None, cve_b: str | None) -> bool:
    """Check if two CVEs belong to the same related group."""
    if not cve_a or not cve_b:
        return False
    a_upper = cve_a.upper()
    b_upper = cve_b.upper()
    return any(a_upper in group and b_upper in group for group in RELATED_CVE_GROUPS)


def finding_dedup_key(finding: dict[str, Any]) -> str:
    """Generate a deduplication key for a finding (normalized for comparison)."""
    template = (finding.get("template-id") or finding.get("name") or "").strip().lower()
    host = (finding.get("host") or finding.get("ip") or "").strip().lower()
    port = str(finding.get("port") or finding.get("portid") or "").strip()
    matched = (finding.get("matched-at") or "").strip().lower()

    # Strip protocol prefixes for URL-based comparisons
    for prefix in ("https://", "http://"):
        if host.startswith(prefix):
            host = host[len(prefix) :]
        if matched.startswith(prefix):
            matched = matched[len(prefix) :]

    # Remove trailing slashes
    host = host.rstrip("/")
    matched = matched.rstrip("/")

    # Normalize implicit ports (80 for http, 443 for https)
    if port in ("80", "443"):
        port = ""

    return f"{template}|{host}|{port}|{matched}"


def normalize_finding(finding: dict[str, Any]) -> dict[str, Any]:
    """Normalize finding fields for consistent comparison (returns copy)."""
    normalized = dict(finding)
    for key in ("name", "template-id", "host", "ip", "matched-at", "description"):
        if key in normalized and isinstance(normalized[key], str):
            normalized[key] = normalized[key].strip().lower()
    return normalized


def is_fuzzy_duplicate(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Check if two findings are fuzzy duplicates.

    Same host+port and >80% description similarity, or related CVEs on same host.
    """
    a_host = a.get("host") or a.get("ip") or ""
    b_host = b.get("host") or b.get("ip") or ""
    a_port = str(a.get("port") or a.get("portid") or "")
    b_port = str(b.get("port") or b.get("portid") or "")

    if a_host != b_host or a_port != b_port:
        return False

    # Check related CVEs
    a_cve = a.get("cve_id") or a.get("cve") or ""
    b_cve = b.get("cve_id") or b.get("cve") or ""
    if a_cve and b_cve and are_related_cves(a_cve, b_cve):
        return True

    a_desc = str(a.get("description") or a.get("name") or "")
    b_desc = str(b.get("description") or b.get("name") or "")

    if not a_desc or not b_desc:
        return False

    # Simple similarity: ratio of common characters
    from difflib import SequenceMatcher

    ratio = SequenceMatcher(None, a_desc, b_desc).ratio()
    return ratio > 0.8


def is_duplicate_finding(findings: list[dict[str, Any]], finding: dict[str, Any]) -> bool:
    """Check for exact or fuzzy duplicates; merge into existing if found.

    Args:
        findings: The existing findings list (mutated on merge).
        finding: The new finding to check.

    Returns:
        True if the finding is a duplicate (existing entry updated), False otherwise.
    """
    dedup_key = finding_dedup_key(finding)

    # Exact duplicates — increment count
    for existing in findings:
        if finding_dedup_key(existing) == dedup_key:
            existing["count"] = existing.get("count", 1) + 1
            return True

    # Fuzzy duplicates (same host+port, similar description)
    for existing in findings:
        if is_fuzzy_duplicate(existing, finding):
            existing["count"] = existing.get("count", 1) + 1
            # Keep the one with more detail
            if len(str(finding)) > len(str(existing)):
                existing.update({k: v for k, v in finding.items() if k != "count"})
            return True

    return False


async def async_is_duplicate_finding(findings: list[dict[str, Any]], finding: dict[str, Any]) -> bool:
    """Async version of is_duplicate_finding that offloads to a thread pool.

    For missions with 200+ findings, the O(n) SequenceMatcher calls can block
    the event loop.  This runs the check in the default executor.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, functools.partial(is_duplicate_finding, findings, finding)
    )
