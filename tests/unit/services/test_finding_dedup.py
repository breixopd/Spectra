"""Tests for app.services.mission.finding_dedup module."""

from spectra_platform.services.mission.finding_dedup import (
    are_related_cves,
    finding_dedup_key,
    is_duplicate_finding,
    is_fuzzy_duplicate,
    normalize_finding,
)


class TestAreRelatedCves:
    def test_related_log4shell_family(self):
        assert are_related_cves("CVE-2021-44228", "CVE-2021-45046") is True

    def test_related_apache_path_traversal(self):
        assert are_related_cves("CVE-2021-41773", "CVE-2021-42013") is True

    def test_unrelated_cves(self):
        assert are_related_cves("CVE-2021-44228", "CVE-2021-41773") is False

    def test_case_insensitive(self):
        assert are_related_cves("cve-2021-44228", "CVE-2021-45046") is True

    def test_none_inputs(self):
        assert are_related_cves(None, "CVE-2021-44228") is False
        assert are_related_cves("CVE-2021-44228", None) is False
        assert are_related_cves(None, None) is False

    def test_empty_strings(self):
        assert are_related_cves("", "CVE-2021-44228") is False
        assert are_related_cves("CVE-2021-44228", "") is False

    def test_same_cve_in_group(self):
        # Same CVE should be related to itself if it's in a group
        assert are_related_cves("CVE-2021-44228", "CVE-2021-44228") is True

    def test_http2_rapid_reset_group(self):
        assert are_related_cves("CVE-2023-44487", "CVE-2024-27316") is True


class TestFindingDedupKey:
    def test_basic_key_generation(self):
        finding = {
            "template-id": "apache-detect",
            "host": "192.168.1.1",
            "port": "8080",
            "matched-at": "/admin",
        }
        key = finding_dedup_key(finding)
        assert key == "apache-detect|192.168.1.1|8080|/admin"

    def test_strips_protocol_from_host(self):
        finding = {"template-id": "test", "host": "https://example.com", "port": ""}
        key = finding_dedup_key(finding)
        assert "https://" not in key
        assert "example.com" in key

    def test_strips_trailing_slashes(self):
        f1 = {"template-id": "test", "host": "example.com/", "port": ""}
        f2 = {"template-id": "test", "host": "example.com", "port": ""}
        assert finding_dedup_key(f1) == finding_dedup_key(f2)

    def test_normalizes_implicit_ports(self):
        f80 = {"template-id": "test", "host": "example.com", "port": "80"}
        f443 = {"template-id": "test", "host": "example.com", "port": "443"}
        f_none = {"template-id": "test", "host": "example.com", "port": ""}
        # Ports 80 and 443 are normalized to empty
        assert finding_dedup_key(f80) == finding_dedup_key(f_none)
        assert finding_dedup_key(f443) == finding_dedup_key(f_none)

    def test_case_insensitive(self):
        f1 = {"template-id": "Apache-Detect", "host": "EXAMPLE.COM"}
        f2 = {"template-id": "apache-detect", "host": "example.com"}
        assert finding_dedup_key(f1) == finding_dedup_key(f2)

    def test_missing_fields_fallback(self):
        # Uses 'name' when 'template-id' is absent, 'ip' when 'host' is absent
        finding = {"name": "vuln-check", "ip": "10.0.0.1", "portid": "22"}
        key = finding_dedup_key(finding)
        assert "vuln-check" in key
        assert "10.0.0.1" in key
        assert "22" in key

    def test_empty_finding(self):
        key = finding_dedup_key({})
        assert key == "|||"

    def test_whitespace_stripped(self):
        finding = {"template-id": "  test  ", "host": "  host  ", "port": "  80  "}
        key = finding_dedup_key(finding)
        assert "  " not in key


class TestNormalizeFinding:
    def test_strips_and_lowercases(self):
        finding = {"name": "  SQL Injection  ", "host": "  EXAMPLE.COM  "}
        normalized = normalize_finding(finding)
        assert normalized["name"] == "sql injection"
        assert normalized["host"] == "example.com"

    def test_preserves_non_string_fields(self):
        finding = {"name": "test", "port": 8080, "count": 3}
        normalized = normalize_finding(finding)
        assert normalized["port"] == 8080
        assert normalized["count"] == 3

    def test_returns_copy(self):
        finding = {"name": "test"}
        normalized = normalize_finding(finding)
        normalized["name"] = "modified"
        assert finding["name"] == "test"


class TestIsFuzzyDuplicate:
    def test_same_host_similar_description(self):
        a = {"host": "192.168.1.1", "port": "80", "description": "SQL injection vulnerability in login form"}
        b = {"host": "192.168.1.1", "port": "80", "description": "SQL injection vulnerability in login page"}
        assert is_fuzzy_duplicate(a, b) is True

    def test_different_hosts_not_duplicate(self):
        a = {"host": "192.168.1.1", "port": "80", "description": "Same description"}
        b = {"host": "192.168.1.2", "port": "80", "description": "Same description"}
        assert is_fuzzy_duplicate(a, b) is False

    def test_different_ports_not_duplicate(self):
        a = {"host": "192.168.1.1", "port": "80", "description": "Same description"}
        b = {"host": "192.168.1.1", "port": "443", "description": "Same description"}
        assert is_fuzzy_duplicate(a, b) is False

    def test_related_cves_same_host(self):
        a = {"host": "target.com", "port": "443", "cve_id": "CVE-2021-44228"}
        b = {"host": "target.com", "port": "443", "cve_id": "CVE-2021-45046"}
        assert is_fuzzy_duplicate(a, b) is True

    def test_very_different_descriptions_not_duplicate(self):
        a = {"host": "192.168.1.1", "port": "80", "description": "SQL injection on login"}
        b = {"host": "192.168.1.1", "port": "80", "description": "XSS reflected in search parameter"}
        assert is_fuzzy_duplicate(a, b) is False

    def test_empty_descriptions_not_duplicate(self):
        a = {"host": "192.168.1.1", "port": "80"}
        b = {"host": "192.168.1.1", "port": "80"}
        assert is_fuzzy_duplicate(a, b) is False

    def test_uses_name_fallback_for_description(self):
        a = {"host": "192.168.1.1", "port": "80", "name": "SQL injection vulnerability found"}
        b = {"host": "192.168.1.1", "port": "80", "name": "SQL injection vulnerability detected"}
        assert is_fuzzy_duplicate(a, b) is True

    def test_uses_ip_fallback_for_host(self):
        a = {"ip": "10.0.0.1", "port": "22", "description": "SSH weak key exchange algorithm detected on server"}
        b = {"ip": "10.0.0.1", "port": "22", "description": "SSH weak key exchange algorithm detected on target"}
        assert is_fuzzy_duplicate(a, b) is True


class TestIsDuplicateFinding:
    def test_exact_duplicate_increments_count(self):
        findings = [
            {"template-id": "apache-detect", "host": "192.168.1.1", "port": "80", "matched-at": "/"},
        ]
        new = {"template-id": "apache-detect", "host": "192.168.1.1", "port": "80", "matched-at": "/"}
        assert is_duplicate_finding(findings, new) is True
        assert findings[0].get("count") == 2

    def test_not_duplicate_returns_false(self):
        findings = [
            {"template-id": "apache-detect", "host": "192.168.1.1", "port": "80"},
        ]
        new = {"template-id": "nginx-detect", "host": "192.168.1.2", "port": "443"}
        assert is_duplicate_finding(findings, new) is False

    def test_empty_findings_list(self):
        findings = []
        new = {"template-id": "test", "host": "10.0.0.1"}
        assert is_duplicate_finding(findings, new) is False

    def test_fuzzy_duplicate_merges(self):
        findings = [
            {"host": "10.0.0.1", "port": "80", "description": "SQL injection in login form", "count": 1},
        ]
        new = {"host": "10.0.0.1", "port": "80", "description": "SQL injection in login page"}
        assert is_duplicate_finding(findings, new) is True
        assert findings[0]["count"] == 2

    def test_fuzzy_duplicate_keeps_more_detailed(self):
        short = {
            "template-id": "sqli-1",
            "host": "10.0.0.1",
            "port": "80",
            "matched-at": "/login",
            "description": "SQL injection vulnerability in login form parameter",
            "count": 1,
        }
        findings = [short]
        detailed = {
            "template-id": "sqli-2",
            "host": "10.0.0.1",
            "port": "80",
            "matched-at": "/auth",
            "description": "SQL injection vulnerability in login form handler",
            "extra_detail": "Found in parameter 'username' via POST request to /login endpoint with error-based technique",
        }
        # Different dedup keys (different template-id/matched-at) => not exact match
        # But same host/port and >80% description similarity => fuzzy match
        # The detailed finding has longer str representation => overwrites fields
        result = is_duplicate_finding(findings, detailed)
        assert result is True
        assert findings[0]["count"] == 2
        assert findings[0]["extra_detail"] is not None

    def test_multiple_exact_duplicates_increment(self):
        findings = [
            {"template-id": "test", "host": "10.0.0.1", "port": "80", "matched-at": ""},
        ]
        for _ in range(5):
            is_duplicate_finding(
                findings,
                {"template-id": "test", "host": "10.0.0.1", "port": "80", "matched-at": ""},
            )
        assert findings[0].get("count") == 6

    def test_single_finding_no_duplicates(self):
        findings = []
        result = is_duplicate_finding(
            findings,
            {"template-id": "unique", "host": "unique.com", "port": "9999"},
        )
        assert result is False

    def test_all_duplicates(self):
        findings = [{"template-id": "t", "host": "h", "port": "1", "matched-at": ""}]
        for _ in range(3):
            assert is_duplicate_finding(findings, {"template-id": "t", "host": "h", "port": "1", "matched-at": ""})
        assert len(findings) == 1
        assert findings[0]["count"] == 4

    def test_mixed_severity_exact_and_fuzzy(self):
        findings = [
            {"template-id": "vuln-a", "host": "10.0.0.1", "port": "80", "matched-at": "", "severity": "high"},
        ]
        # Exact duplicate
        assert is_duplicate_finding(
            findings,
            {"template-id": "vuln-a", "host": "10.0.0.1", "port": "80", "matched-at": "", "severity": "critical"},
        )
        assert findings[0]["count"] == 2
        # Non-duplicate
        assert not is_duplicate_finding(
            findings,
            {"template-id": "other", "host": "10.0.0.2", "port": "443", "matched-at": "/api"},
        )
