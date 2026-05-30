"""Tests for the HTML report generator."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectra_mission.report_generator import (
    SEVERITY_COLORS,
    SEVERITY_ORDER,
    _count_severities,
    _sort_findings,
    generate_html_report,
    save_report,
)


class TestCountSeverities:
    def test_empty_findings(self):
        assert _count_severities([]) == {}

    def test_single_severity(self):
        findings = [{"severity": "high"}, {"severity": "high"}]
        assert _count_severities(findings) == {"high": 2}

    def test_mixed_severities(self):
        findings = [
            {"severity": "critical"},
            {"severity": "high"},
            {"severity": "high"},
            {"severity": "medium"},
            {"severity": "low"},
            {"severity": "info"},
        ]
        counts = _count_severities(findings)
        assert counts == {"critical": 1, "high": 2, "medium": 1, "low": 1, "info": 1}

    def test_missing_severity_defaults_to_info(self):
        findings = [{}]
        counts = _count_severities(findings)
        assert counts == {"info": 1}

    def test_case_normalization(self):
        findings = [{"severity": "HIGH"}, {"severity": "High"}]
        counts = _count_severities(findings)
        assert counts == {"high": 2}


class TestSortFindings:
    def test_empty_list(self):
        assert _sort_findings([]) == []

    def test_sorts_by_severity(self):
        findings = [
            {"severity": "low", "title": "L"},
            {"severity": "critical", "title": "C"},
            {"severity": "medium", "title": "M"},
            {"severity": "high", "title": "H"},
        ]
        sorted_f = _sort_findings(findings)
        assert sorted_f[0]["title"] == "C"
        assert sorted_f[1]["title"] == "H"
        assert sorted_f[2]["title"] == "M"
        assert sorted_f[3]["title"] == "L"

    def test_unknown_severity_at_end(self):
        findings = [
            {"severity": "unknown", "title": "U"},
            {"severity": "critical", "title": "C"},
        ]
        sorted_f = _sort_findings(findings)
        assert sorted_f[0]["title"] == "C"
        assert sorted_f[-1]["title"] == "U"


class TestGenerateHtmlReport:
    def test_basic_report(self):
        data = {
            "mission": {"id": "m1", "name": "Test Mission", "target": "10.0.0.1"},
            "findings": [],
        }
        html = generate_html_report(data)
        assert "<!DOCTYPE html>" in html
        assert "Test Mission" in html
        assert "10.0.0.1" in html

    def test_report_with_findings(self):
        data = {
            "mission": {"id": "m1", "name": "Test", "target": "t1"},
            "findings": [
                {"title": "SQL Injection", "severity": "critical", "type": "sqli", "description": "Found SQLi"},
                {"title": "XSS", "severity": "high", "type": "xss", "description": "Reflected XSS"},
            ],
        }
        html = generate_html_report(data)
        assert "SQL Injection" in html
        assert "XSS" in html
        assert "sev-critical" in html
        assert "sev-high" in html

    def test_report_severity_grouping(self):
        data = {
            "mission": {"id": "m1", "target": "t1"},
            "findings": [
                {"title": "Low1", "severity": "low"},
                {"title": "Critical1", "severity": "critical"},
            ],
        }
        html = generate_html_report(data)
        # Critical should appear before low in the table
        crit_pos = html.index("Critical1")
        low_pos = html.index("Low1")
        assert crit_pos < low_pos

    def test_empty_mission_report(self):
        data = {"mission": {}, "findings": []}
        html = generate_html_report(data)
        assert "<!DOCTYPE html>" in html
        assert "N/A" in html

    def test_report_with_attack_surface(self):
        data = {
            "mission": {"id": "m1", "target": "t1"},
            "findings": [],
            "attack_surface": {
                "services": [{"port": 80, "service": "http", "product": "Apache"}],
                "technologies": ["PHP", "MySQL"],
                "os": "Linux",
            },
        }
        html = generate_html_report(data)
        assert "Apache" in html
        assert "PHP" in html
        assert "Linux" in html

    def test_report_with_tools_used(self):
        data = {
            "mission": {"id": "m1", "target": "t1"},
            "findings": [],
            "tools_used": ["nmap", "nuclei", "sqlmap"],
        }
        html = generate_html_report(data)
        assert "nmap" in html
        assert "nuclei" in html

    def test_report_with_timeline(self):
        data = {
            "mission": {"id": "m1", "target": "t1"},
            "findings": [],
            "timeline": [
                {"time": "10:00", "phase": "recon", "event": "Started scan"},
            ],
        }
        html = generate_html_report(data)
        assert "Started scan" in html

    def test_report_with_mitre(self):
        data = {
            "mission": {"id": "m1", "target": "t1"},
            "findings": [],
            "mitre_techniques": [
                {"id": "T1055", "name": "Process Injection", "tactic": "Defense Evasion"},
            ],
        }
        html = generate_html_report(data)
        assert "T1055" in html
        assert "Process Injection" in html

    def test_report_has_generated_timestamp(self):
        data = {"mission": {"id": "m1", "target": "t1"}, "findings": []}
        html = generate_html_report(data)
        assert "Generated" in html
        assert "UTC" in html

    def test_report_contains_directive(self):
        data = {
            "mission": {"id": "m1", "target": "t1", "directive": "Full pentest of web app"},
            "findings": [],
        }
        html = generate_html_report(data)
        assert "Full pentest of web app" in html


class TestSaveReport:
    @pytest.mark.asyncio
    async def test_save_creates_file(self, tmp_path):
        mock_storage = MagicMock()
        mock_storage.upload = AsyncMock(return_value="s3://spectra-missions/m1/reports/report.html")
        with patch("spectra_mission.report_generator.get_storage_service", return_value=mock_storage):
            with patch("spectra_mission.report_generator._get_default_secret", return_value="test-key"):
                path = await save_report("m1", "<html>test</html>")
                assert isinstance(path, str)
                assert "m1" in path
                mock_storage.upload.assert_called_once()
                call_args = mock_storage.upload.call_args
                assert call_args[0][1] == "m1/reports/report.html"


class TestSeverityConstants:
    def test_severity_order_complete(self):
        expected = {"critical", "high", "medium", "low", "info"}
        assert set(SEVERITY_ORDER.keys()) == expected

    def test_severity_colors_complete(self):
        expected = {"critical", "high", "medium", "low", "info"}
        assert set(SEVERITY_COLORS.keys()) == expected

    def test_critical_is_first(self):
        assert SEVERITY_ORDER["critical"] == 0

    def test_info_is_last(self):
        assert SEVERITY_ORDER["info"] == 4
