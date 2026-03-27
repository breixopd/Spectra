"""Tests for manual mode backend services and API endpoints."""

import json

import pytest

from app.services.system.checklists import (
    BUILTIN_CHECKLISTS,
    get_checklist,
    list_checklists,
)
from app.services.system.cvss import calculate_cvss31
from app.services.system.gtfobins import GTFOBINS, search_gtfobins
from app.services.system.payloads import (
    LFI_PAYLOADS,
    SQLI_PAYLOADS,
    XSS_PAYLOADS,
    get_payloads,
    list_payload_types,
)
from app.services.system.report_templates import (
    REPORT_TEMPLATES,
    generate_report_data,
    get_report_template,
    list_report_templates,
)

# ===== Checklists =====


class TestChecklists:
    def test_list_checklists_returns_all(self):
        result = list_checklists()
        assert len(result) == len(BUILTIN_CHECKLISTS)
        ids = {c["id"] for c in result}
        assert "owasp_top10_2021" in ids
        assert "network_pentest" in ids
        assert "api_security" in ids
        assert "ad_pentest" in ids
        assert "ptes" in ids

    def test_list_checklists_has_required_fields(self):
        for c in list_checklists():
            assert "id" in c
            assert "name" in c
            assert "description" in c

    def test_get_checklist_found(self):
        result = get_checklist("owasp_top10_2021")
        assert result is not None
        assert result["id"] == "owasp_top10_2021"
        assert result["name"] == "OWASP Top 10 (2021)"
        assert len(result["categories"]) == 10

    def test_get_checklist_not_found(self):
        assert get_checklist("nonexistent") is None

    def test_owasp_checklist_categories_have_items(self):
        cl = get_checklist("owasp_top10_2021")
        for cat in cl["categories"]:
            assert "name" in cat
            assert len(cat["items"]) > 0
            for item in cat["items"]:
                assert "id" in item
                assert "text" in item

    def test_network_pentest_has_five_categories(self):
        cl = get_checklist("network_pentest")
        assert len(cl["categories"]) == 5

    def test_ptes_has_seven_phases(self):
        cl = get_checklist("ptes")
        assert len(cl["categories"]) == 7


# ===== CVSS Calculator =====


class TestCVSSCalculator:
    def test_critical_score(self):
        result = calculate_cvss31("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")
        assert result["base_score"] == 9.8
        assert result["severity"] == "Critical"

    def test_high_score(self):
        result = calculate_cvss31("CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H")
        assert result["base_score"] == 8.8
        assert result["severity"] == "High"

    def test_medium_score(self):
        result = calculate_cvss31("CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:U/C:L/I:L/A:N")
        assert result["base_score"] == 5.4
        assert result["severity"] == "Medium"

    def test_low_score(self):
        result = calculate_cvss31("CVSS:3.1/AV:P/AC:H/PR:H/UI:R/S:U/C:L/I:N/A:N")
        assert result["severity"] == "Low"
        assert result["base_score"] <= 3.9

    def test_none_score(self):
        result = calculate_cvss31("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N")
        assert result["base_score"] == 0.0
        assert result["severity"] == "None"

    def test_scope_changed(self):
        result = calculate_cvss31("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H")
        assert result["base_score"] == 10.0
        assert result["severity"] == "Critical"

    def test_result_has_all_fields(self):
        result = calculate_cvss31("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")
        assert "base_score" in result
        assert "severity" in result
        assert "impact_subscore" in result
        assert "exploitability_subscore" in result
        assert "vector" in result

    def test_invalid_vector(self):
        with pytest.raises(ValueError, match="Invalid CVSS"):
            calculate_cvss31("not-a-vector")

    def test_invalid_metric_values(self):
        with pytest.raises(ValueError, match="Invalid CVSS"):
            calculate_cvss31("CVSS:3.1/AV:X/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")

    def test_cvss30_accepted(self):
        # CVSS:3.0 prefix should also be accepted
        result = calculate_cvss31("CVSS:3.0/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")
        assert result["base_score"] == 9.8

    def test_max_exploitability(self):
        result = calculate_cvss31("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")
        assert result["exploitability_subscore"] > 0


# ===== Payloads =====


class TestPayloads:
    def test_list_payload_types(self):
        types = list_payload_types()
        assert "lfi" in types
        assert "sqli" in types
        assert "xss" in types

    def test_get_lfi_payloads(self):
        payloads = get_payloads("lfi")
        assert len(payloads) == len(LFI_PAYLOADS)
        assert all("name" in p and "payload" in p for p in payloads)

    def test_get_sqli_payloads(self):
        payloads = get_payloads("sqli")
        assert len(payloads) == len(SQLI_PAYLOADS)
        assert all("category" in p for p in payloads)

    def test_get_xss_payloads(self):
        payloads = get_payloads("xss")
        assert len(payloads) == len(XSS_PAYLOADS)

    def test_get_unknown_type(self):
        assert get_payloads("unknown") == []

    def test_case_insensitive(self):
        assert get_payloads("LFI") == get_payloads("lfi")


# ===== GTFOBins =====


class TestGTFOBins:
    def test_search_no_filter(self):
        results = search_gtfobins()
        assert len(results) == len(GTFOBINS)

    def test_search_by_name(self):
        results = search_gtfobins(query="python")
        assert len(results) >= 2
        assert all("python" in r["binary"] for r in results)

    def test_search_by_function(self):
        results = search_gtfobins(function_filter="suid")
        assert len(results) > 0
        assert all("suid" in r["functions"] for r in results)

    def test_combined_search(self):
        results = search_gtfobins(query="vim", function_filter="shell")
        assert len(results) >= 1
        assert all("vim" in r["binary"] for r in results)

    def test_search_no_match(self):
        assert search_gtfobins(query="nonexistentbinary") == []

    def test_entries_have_binary(self):
        for entry in GTFOBINS:
            assert "binary" in entry
            assert "functions" in entry


# ===== Report Templates =====


class TestReportTemplates:
    def test_list_templates(self):
        templates = list_report_templates()
        assert len(templates) == len(REPORT_TEMPLATES)
        ids = {t["id"] for t in templates}
        assert "executive" in ids
        assert "technical" in ids
        assert "compliance" in ids

    def test_get_template_found(self):
        t = get_report_template("executive")
        assert t is not None
        assert t["name"] == "Executive Summary"
        assert "sections" in t

    def test_get_template_not_found(self):
        assert get_report_template("nonexistent") is None

    def test_generate_report_unknown_template(self, tmp_path):
        session_file = tmp_path / "session.json"
        session_file.write_text(json.dumps({"id": "s1", "name": "Session", "target": "127.0.0.1", "findings": [], "tools_used": [], "command_history": []}))
        with pytest.raises(ValueError, match="Unknown template"):
            generate_report_data(session_file, "bad_template")

    def test_generate_report_missing_session(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            generate_report_data(tmp_path / "missing.json", "executive")

    def test_generate_report_success(self, tmp_path):
        session_file = tmp_path / "test.json"
        session_file.write_text(
            json.dumps(
                {
                    "id": "test",
                    "name": "Test Session",
                    "target": "192.168.1.1",
                    "findings": [
                        {"title": "SQLi", "severity": "high"},
                        {"title": "XSS", "severity": "medium"},
                    ],
                    "tools_used": ["nmap"],
                    "command_history": [],
                }
            )
        )
        result = generate_report_data(session_file, "technical")
        assert result["template"] == "technical"
        assert result["total_findings"] == 2
        assert result["severity_counts"]["high"] == 1
        assert result["severity_counts"]["medium"] == 1
