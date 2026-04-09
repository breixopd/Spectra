"""Tests for OsintSanitizer privacy safeguards."""

from app.services.ai.agents.recon_intel import OsintSanitizer


def test_sanitize_ips():
    """IPv4 addresses redacted."""
    text = "Found host at 8.8.8.8 running nginx"
    result = OsintSanitizer.sanitize(text)
    assert "8.8.8.8" not in result
    assert "[REDACTED_IP]" in result
    assert "nginx" in result


def test_sanitize_internal_ips():
    """RFC1918 addresses redacted."""
    for ip in ("10.0.0.1", "192.168.1.100", "172.16.5.2"):
        result = OsintSanitizer.sanitize(f"host {ip} is alive")
        assert ip not in result
        assert "[REDACTED_IP]" in result


def test_sanitize_domains():
    """Domains redacted."""
    text = "Target is example.com running Apache on web.target.io"
    result = OsintSanitizer.sanitize(text)
    assert "example.com" not in result
    assert "target.io" not in result
    assert "[REDACTED_DOMAIN]" in result


def test_sanitize_preserves_safe_domains():
    """nvd.nist.gov, cisa.gov not redacted."""
    text = "Reference: nvd.nist.gov and www.cisa.gov and exploit-db.com"
    result = OsintSanitizer.sanitize(text)
    assert "nvd.nist.gov" in result
    assert "www.cisa.gov" in result
    assert "exploit-db.com" in result


def test_validate_safe_clean_data():
    """CVE-only data passes validation."""
    data = {"cve_ids": ["CVE-2024-1234", "CVE-2023-5678"], "query_type": "cve_lookup"}
    assert OsintSanitizer.validate_safe_for_external(data) is True


def test_validate_blocks_ip_data():
    """Data with IPs blocked."""
    data = {"target": "192.168.1.1", "query": "scan"}
    assert OsintSanitizer.validate_safe_for_external(data) is False


def test_validate_blocks_domain_data():
    """Data with target domains blocked."""
    data = {"host": "target.example.com", "query": "lookup"}
    assert OsintSanitizer.validate_safe_for_external(data) is False


def test_sanitize_mixed_content():
    """Complex text with mix of IPs, domains, CVEs."""
    text = (
        "CVE-2024-1234 affects 10.0.0.5 and example.com. "
        "See nvd.nist.gov for details. Also 203.0.113.42 and sub.target.org."
    )
    result = OsintSanitizer.sanitize(text)

    # CVE identifiers preserved
    assert "CVE-2024-1234" in result
    # Safe domain preserved
    assert "nvd.nist.gov" in result
    # IPs and target domains redacted
    assert "10.0.0.5" not in result
    assert "203.0.113.42" not in result
    assert "example.com" not in result
    assert "sub.target.org" not in result
    assert "[REDACTED_IP]" in result
    assert "[REDACTED_DOMAIN]" in result
