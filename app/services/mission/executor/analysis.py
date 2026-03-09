"""Analysis helpers for Mission Executor."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.attack_surface import AttackVector


# Performance Optimization: Pre-compute lowercase indicators to avoid recalculating
# them inside the hot path during output matching.
SUCCESS_INDICATORS_LOWER = [
    "uid=",
    "gid=",
    "root@",
    "administrator",
    "meterpreter session",
    "command shell session",
    "sql injection found",
    "database dumped",
    "vulnerable:",
    "[+]",
]

def check_exploit_success(output: str) -> bool:
    """Check if exploit output indicates success."""
    output_lower = output.lower()
    return any(ind in output_lower for ind in SUCCESS_INDICATORS_LOWER)


def detect_blocking(stderr: str) -> str | None:
    """Detect what blocked the exploit."""
    stderr_lower = stderr.lower()
    if "timeout" in stderr_lower or "timed out" in stderr_lower:
        return "timeout"
    if "connection refused" in stderr_lower:
        return "firewall"
    if "403" in stderr or "blocked" in stderr_lower:
        return "waf"
    if "antivirus" in stderr_lower or "malware" in stderr_lower:
        return "av"
    if "connection reset" in stderr_lower:
        return "connection_reset"
    if "host unreachable" in stderr_lower or "no route" in stderr_lower:
        return "network"
    if "permission denied" in stderr_lower:
        return "permission"
    if "authentication" in stderr_lower:
        return "auth_required"
    return None


def suggest_retry(result: Any, vector: AttackVector) -> str | None:
    """Suggest retry strategy based on failure analysis."""
    stderr = result.stderr or ""
    stdout = result.stdout or ""
    combined = (stderr + stdout).lower()

    # Timeout issues
    if "timeout" in combined or "timed out" in combined:
        return "Increase timeout or try slower scan rate"

    # WAF/Firewall blocking
    if "403" in stderr or "forbidden" in combined:
        return "Try WAF bypass encoding or alternative path"

    # Rate limiting
    if "429" in stderr or "rate limit" in combined or "too many" in combined:
        return "Add delay between requests or reduce concurrency"

    # Connection issues
    if "connection refused" in combined:
        return "Service may be down, try alternative port or wait"
    if "connection reset" in combined:
        return "Try slower scan rate or different approach"

    # Authentication required
    if (
        "401" in stderr
        or "unauthorized" in combined
        or "authentication required" in combined
    ):
        return "Credentials needed, try default creds or brute force"

    # Service not vulnerable
    if "not vulnerable" in combined or "patched" in combined:
        return "Service appears patched, try alternative exploit"

    # More payloads available
    if vector.payloads and len(vector.attempts) < len(vector.payloads) - 1:
        remaining = len(vector.payloads) - len(vector.attempts) - 1
        return f"Try different payload ({remaining} remaining)"

    # Generic suggestions based on attempt count
    if len(vector.attempts) == 1:
        return "First attempt failed, try with different parameters"
    elif len(vector.attempts) < vector.max_attempts:
        return f"Retry with modified approach ({vector.max_attempts - len(vector.attempts)} attempts remaining)"

    return None


def analyze_unexpected_output(
    stdout: str,
    stderr: str,
    expected_patterns: list[str] | None = None,
) -> dict[str, Any]:
    """
    Analyze tool output for unexpected results and extract useful information.

    Returns a dict with:
    - has_errors: bool
    - error_type: str or None
    - interesting_findings: list of strings
    - suggestions: list of strings
    """
    analysis = {
        "has_errors": False,
        "error_type": None,
        "interesting_findings": [],
        "suggestions": [],
    }

    combined = (stdout + stderr).lower()

    # Check for common error patterns
    error_patterns = {
        "network": ["host unreachable", "network is unreachable", "no route to host"],
        "timeout": ["timeout", "timed out", "connection timed out"],
        "permission": ["permission denied", "access denied", "not permitted"],
        "auth": ["authentication failed", "login failed", "invalid credentials"],
        "service_down": ["connection refused", "service unavailable", "not responding"],
        "rate_limited": ["rate limit", "too many requests", "429"],
        "blocked": ["blocked", "banned", "firewall", "filtered"],
    }

    for error_type, patterns in error_patterns.items():
        if any(p in combined for p in patterns):
            analysis["has_errors"] = True
            analysis["error_type"] = error_type
            break

    # Extract interesting findings even from failed attempts
    interesting_patterns = [
        ("version", r"version[:\s]+([^\s\n]+)"),
        ("banner", r"banner[:\s]+(.+)"),
        ("server", r"server[:\s]+([^\s\n]+)"),
        ("os", r"os[:\s]+([^\s\n]+)"),
        ("service", r"service[:\s]+([^\s\n]+)"),
    ]

    for name, pattern in interesting_patterns:
        matches = re.findall(pattern, combined, re.IGNORECASE)
        if matches:
            analysis["interesting_findings"].extend(
                [f"{name}: {m}" for m in matches[:3]]
            )

    # Generate suggestions based on analysis
    if analysis["error_type"] == "timeout":
        analysis["suggestions"].append("Increase timeout or use async scanning")
    elif analysis["error_type"] == "rate_limited":
        analysis["suggestions"].append("Add delay between requests")
    elif analysis["error_type"] == "blocked":
        analysis["suggestions"].append(
            "Try from different IP or use evasion techniques"
        )
    elif analysis["error_type"] == "auth":
        analysis["suggestions"].append("Try default credentials or brute force")

    return analysis


def auto_expand_scope(findings: list[dict[str, Any]], current_scope: dict[str, Any]) -> list[dict[str, Any]]:
    """Suggest scope expansions based on findings.

    Returns a list of expansion dicts with type, value, and source.
    """
    expansions: list[dict[str, Any]] = []
    seen: set[str] = set()
    current_values = {str(v) for v in current_scope.values()} if current_scope else set()

    for finding in findings:
        ftype = finding.get("type", "")
        value = finding.get("value", "")

        if not value or value in seen:
            continue

        # New hosts discovered via DNS/subdomain tools
        if ftype == "subdomain" and value not in current_values:
            expansions.append({"type": "domain", "value": value, "source": "auto-discovered"})
            seen.add(value)

        # New IPs from pivot/enumeration
        if ftype == "host" and value not in current_values:
            expansions.append({"type": "ip", "value": value, "source": "pivot-discovered"})
            seen.add(value)

    return expansions
