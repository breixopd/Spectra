"""Tests for CVE Intelligence Service."""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.cve_intel import (
    CVE_CACHE_TTL,
    _cache_path,
    _infer_vuln_type,
    _load_cache,
    _save_cache,
    enrich_cve_with_exploits,
    fetch_cves_from_nvd,
    get_cve_context_for_services,
    lookup_cves,
    lookup_cves_live,
    reload_cve_knowledge_base,
)

# Sample knowledge base data for tests — loaded via _load_cve_knowledge_base
_TEST_CVE_KB = [
    {"cve": "CVE-2021-41773", "product": "apache", "versions": "2.4.49", "type": "path_traversal", "severity": "critical", "description": "Path traversal in Apache 2.4.49 via %2e encoding"},
    {"cve": "CVE-2021-42013", "product": "apache", "versions": "2.4.49,2.4.50", "type": "rce", "severity": "critical", "description": "RCE via path traversal in Apache 2.4.49-2.4.50"},
    {"cve": "CVE-2019-0211", "product": "apache", "versions": "2.4.17-2.4.38", "type": "privilege_escalation", "severity": "high", "description": "Local privilege escalation in Apache 2.4.17-2.4.38"},
    {"cve": "CVE-2017-9798", "product": "apache", "versions": "2.2.x,2.4.x", "type": "info_leak", "severity": "medium", "description": "Optionsbleed - memory leak via OPTIONS method"},
    {"cve": "CVE-2024-6387", "product": "openssh", "versions": "8.5p1-9.7p1", "type": "rce", "severity": "critical", "description": "regreSSHion - unauthenticated RCE in OpenSSH signal handler race"},
    {"cve": "CVE-2012-2122", "product": "mysql", "versions": "5.1.x,5.5.x", "type": "auth_bypass", "severity": "critical", "description": "Authentication bypass via timing attack"},
    {"cve": "CVE-2022-21661", "product": "wordpress", "versions": "<5.8.3", "type": "sqli", "severity": "high", "description": "SQL injection in WP_Query"},
    {"cve": "CVE-2021-44228", "product": "log4j", "versions": "2.0-2.14.1", "type": "rce", "severity": "critical", "description": "Log4Shell - JNDI injection RCE via ${jndi:ldap://}"},
    {"cve": "CVE-2017-0144", "product": "smb", "versions": "smbv1", "type": "rce", "severity": "critical", "description": "EternalBlue - MS17-010 SMBv1 remote code execution"},
]


@pytest.fixture(autouse=True)
def _mock_cve_kb(tmp_path):
    """Write test knowledge base and mock the loader to use it."""
    kb_path = tmp_path / "cve_knowledge_base.json"
    kb_path.write_text(json.dumps(_TEST_CVE_KB))

    import app.services.ai.cve_intel as mod
    mod._cve_knowledge_base = None  # Reset cache
    with patch("app.services.ai.cve_intel._load_cve_knowledge_base", return_value=_TEST_CVE_KB):
        yield
    mod._cve_knowledge_base = None


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


# --- Extended CVE Intel Tests ---


class TestInferVulnType:
    def test_rce(self):
        assert _infer_vuln_type("Remote code execution via buffer overflow") == "rce"

    def test_sqli(self):
        assert _infer_vuln_type("SQL injection in login form") == "sqli"

    def test_xss(self):
        assert _infer_vuln_type("Cross-site scripting in search") == "xss"

    def test_path_traversal(self):
        assert _infer_vuln_type("Path traversal allows file read") == "path_traversal"

    def test_auth_bypass(self):
        assert _infer_vuln_type("Authentication bypass via timing attack") == "auth_bypass"

    def test_unknown(self):
        assert _infer_vuln_type("Some generic vulnerability") == "unknown"

    def test_privilege_escalation(self):
        assert _infer_vuln_type("Local privilege escalation") == "privilege_escalation"


class TestCVECache:
    def test_cache_path_sanitizes(self):
        path = _cache_path("test keyword/special")
        assert "/" not in path.name or str(path).endswith(".json")

    def test_save_and_load_cache(self, tmp_path):
        results = [{"cve": "CVE-2021-1234", "severity": "high"}]
        with patch("app.services.ai.cve_intel.CVE_CACHE_DIR", tmp_path):
            _save_cache("test_keyword", results)
            loaded = _load_cache("test_keyword")
            assert loaded is not None
            assert len(loaded) == 1
            assert loaded[0]["cve"] == "CVE-2021-1234"

    def test_load_expired_cache(self, tmp_path):
        with patch("app.services.ai.cve_intel.CVE_CACHE_DIR", tmp_path):
            _save_cache("old_keyword", [{"cve": "CVE-2020-0001"}])
            # Make it expired
            cache_file = tmp_path / "old_keyword.json"
            data = json.loads(cache_file.read_text())
            data["cached_at"] = time.time() - CVE_CACHE_TTL - 100
            cache_file.write_text(json.dumps(data))

            loaded = _load_cache("old_keyword")
            assert loaded is None

    def test_load_missing_cache(self, tmp_path):
        with patch("app.services.ai.cve_intel.CVE_CACHE_DIR", tmp_path):
            assert _load_cache("nonexistent") is None

    def test_load_corrupt_cache(self, tmp_path):
        with patch("app.services.ai.cve_intel.CVE_CACHE_DIR", tmp_path):
            bad_file = tmp_path / "corrupt.json"
            bad_file.write_text("not json{{{")
            assert _load_cache("corrupt") is None


class TestFetchCVEsFromNVD:
    @pytest.mark.asyncio
    async def test_cached_result_returned(self, tmp_path):
        cached = [{"cve": "CVE-2021-CACHED", "severity": "high"}]
        with patch("app.services.ai.cve_intel._load_cache", return_value=cached):
            result = await fetch_cves_from_nvd("apache")
            assert result == cached

    @pytest.mark.asyncio
    async def test_api_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "vulnerabilities": [
                {
                    "cve": {
                        "id": "CVE-2021-99999",
                        "descriptions": [{"lang": "en", "value": "Test vuln"}],
                        "metrics": {
                            "cvssMetricV31": [
                                {"cvssData": {"baseSeverity": "HIGH", "baseScore": 8.5}}
                            ]
                        },
                        "configurations": [],
                    }
                }
            ]
        }

        with patch("app.services.ai.cve_intel._load_cache", return_value=None):
            with patch("app.services.ai.cve_intel._save_cache"):
                with patch("app.services.ai.cve_intel._last_nvd_request", 0):
                    with patch("httpx.AsyncClient") as MockClient:
                        mock_client = AsyncMock()
                        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
                        mock_client.get = AsyncMock(return_value=mock_response)

                        result = await fetch_cves_from_nvd("test")
                        assert len(result) == 1
                        assert result[0]["cve"] == "CVE-2021-99999"
                        assert result[0]["severity"] == "high"

    @pytest.mark.asyncio
    async def test_api_rate_limited(self):
        mock_response = MagicMock()
        mock_response.status_code = 403

        with patch("app.services.ai.cve_intel._load_cache", return_value=None):
            with patch("app.services.ai.cve_intel._last_nvd_request", 0):
                with patch("httpx.AsyncClient") as MockClient:
                    mock_client = AsyncMock()
                    MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                    MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
                    mock_client.get = AsyncMock(return_value=mock_response)

                    result = await fetch_cves_from_nvd("test")
                    assert result == []

    @pytest.mark.asyncio
    async def test_api_timeout(self):
        import httpx
        with patch("app.services.ai.cve_intel._load_cache", return_value=None):
            with patch("app.services.ai.cve_intel._last_nvd_request", 0):
                with patch("httpx.AsyncClient") as MockClient:
                    mock_client = AsyncMock()
                    MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                    MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
                    mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

                    result = await fetch_cves_from_nvd("test")
                    assert result == []

    @pytest.mark.asyncio
    async def test_api_generic_error(self):
        with patch("app.services.ai.cve_intel._load_cache", return_value=None):
            with patch("app.services.ai.cve_intel._last_nvd_request", 0):
                with patch("httpx.AsyncClient") as MockClient:
                    mock_client = AsyncMock()
                    MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                    MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
                    mock_client.get = AsyncMock(side_effect=RuntimeError("network fail"))

                    result = await fetch_cves_from_nvd("test")
                    assert result == []


class TestReloadKnowledgeBase:
    def test_reload_resets_cache(self):
        import app.services.ai.cve_intel as mod
        old = mod._cve_knowledge_base
        with patch("app.services.ai.cve_intel._load_cve_knowledge_base", return_value=_TEST_CVE_KB):
            count = reload_cve_knowledge_base()
            assert count == len(_TEST_CVE_KB)
        mod._cve_knowledge_base = old


class TestEnrichCVE:
    def test_enrich_adds_exploit_fields(self):
        cve = {"cve": "CVE-2021-44228", "severity": "critical"}
        with patch("app.services.ai.cve_intel.get_metasploit_modules", return_value=[
            {"source": "metasploit", "module": "test"}
        ]):
            with patch("app.services.ai.exploit_db.get_exploit_db") as mock_db:
                db = mock_db.return_value
                db.is_kev.return_value = True

                enriched = enrich_cve_with_exploits(cve)
                assert enriched["exploit_available"]
                assert enriched["exploit_count"] == 1
                assert enriched["kev_exploited"]
                assert len(enriched["metasploit_modules"]) == 1

    def test_enrich_no_exploits(self):
        cve = {"cve": "CVE-9999-0001", "severity": "low"}
        with patch("app.services.ai.cve_intel.get_metasploit_modules", return_value=[]):
            with patch("app.services.ai.exploit_db.get_exploit_db") as mock_db:
                db = mock_db.return_value
                db.is_kev.return_value = False

                enriched = enrich_cve_with_exploits(cve)
                assert not enriched["exploit_available"]
                assert enriched["exploit_count"] == 0


class TestLookupCVEsLive:
    @pytest.mark.asyncio
    async def test_merges_builtin_and_live(self):
        live = [{"cve": "CVE-2023-LIVE", "severity": "high", "products": []}]
        with patch("app.services.ai.cve_intel.fetch_cves_from_nvd", new_callable=AsyncMock, return_value=live):
            with patch("app.services.ai.cve_intel.enrich_cve_with_exploits", side_effect=lambda x: x):
                results = await lookup_cves_live(product="Apache", version="2.4.49")
                cve_ids = [r["cve"] for r in results]
                assert "CVE-2021-41773" in cve_ids  # builtin
                assert "CVE-2023-LIVE" in cve_ids  # live

    @pytest.mark.asyncio
    async def test_deduplicates(self):
        # Live returns same CVE as builtin
        live = [{"cve": "CVE-2021-41773", "severity": "critical", "products": []}]
        with patch("app.services.ai.cve_intel.fetch_cves_from_nvd", new_callable=AsyncMock, return_value=live):
            with patch("app.services.ai.cve_intel.enrich_cve_with_exploits", side_effect=lambda x: x):
                results = await lookup_cves_live(product="Apache")
                ids = [r["cve"] for r in results]
                assert ids.count("CVE-2021-41773") == 1

    @pytest.mark.asyncio
    async def test_empty_search_returns_builtin_only(self):
        results = await lookup_cves_live()
        assert results == []

    @pytest.mark.asyncio
    async def test_live_failure_falls_back(self):
        with patch("app.services.ai.cve_intel.fetch_cves_from_nvd", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
            with patch("app.services.ai.cve_intel.enrich_cve_with_exploits", side_effect=lambda x: x):
                results = await lookup_cves_live(product="Apache")
                assert len(results) > 0  # Falls back to builtin
