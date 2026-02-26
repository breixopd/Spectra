"""Tests for CVE Intelligence Service."""

import pytest
from app.services.ai.cve_intel import lookup_cves, get_cve_context_for_services


class TestLookupCVEs:

    def test_apache_lookup(self):
        results = lookup_cves(product="Apache")
        assert len(results) > 0
        assert any("CVE-2021-41773" in r["cve"] for r in results)

    def test_version_match_priority(self):
        results = lookup_cves(product="Apache", version="2.4.49")
        assert results[0]["version_match"] is True
        assert results[0]["cve"] == "CVE-2021-41773"

    def test_openssh_lookup(self):
        results = lookup_cves(product="OpenSSH")
        assert len(results) > 0
        assert any("regreSSHion" in r.get("description", "") for r in results)

    def test_service_lookup(self):
        results = lookup_cves(service="mysql")
        assert len(results) > 0

    def test_unknown_product(self):
        results = lookup_cves(product="SuperObscureSoftware")
        assert len(results) == 0

    def test_empty_query(self):
        assert lookup_cves() == []

    def test_severity_sorting(self):
        results = lookup_cves(product="apache")
        severities = [r["severity"] for r in results]
        # Critical should come before medium
        if "critical" in severities and "medium" in severities:
            assert severities.index("critical") < severities.index("medium")

    def test_wordpress_cves(self):
        results = lookup_cves(product="WordPress")
        assert any("CVE-2022-21661" in r["cve"] for r in results)

    def test_log4j(self):
        results = lookup_cves(product="log4j")
        assert any("Log4Shell" in r["description"] for r in results)

    def test_smb_eternalblue(self):
        results = lookup_cves(service="smb")
        assert any("EternalBlue" in r["description"] for r in results)


class TestGetCVEContext:

    def test_generates_context_for_apache(self):
        services = [{"service": "http", "product": "Apache", "version": "2.4.49", "port": 80}]
        ctx = get_cve_context_for_services(services)
        assert "CVE-2021-41773" in ctx
        assert "VERSION MATCH" in ctx
        assert "Known CVEs" in ctx

    def test_empty_services(self):
        assert get_cve_context_for_services([]) == ""

    def test_unknown_service(self):
        services = [{"service": "custom", "product": "MyApp", "version": "1.0", "port": 9999}]
        assert get_cve_context_for_services(services) == ""

    def test_multiple_services(self):
        services = [
            {"service": "http", "product": "Apache", "version": "2.4.25", "port": 80},
            {"service": "ssh", "product": "OpenSSH", "version": "8.9", "port": 22},
        ]
        ctx = get_cve_context_for_services(services)
        assert "Apache" in ctx
        assert "OpenSSH" in ctx

    def test_openssh_regresshion(self):
        services = [{"service": "ssh", "product": "OpenSSH", "version": "9.3p1", "port": 22}]
        ctx = get_cve_context_for_services(services)
        assert "CVE-2024-6387" in ctx
