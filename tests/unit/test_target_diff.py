"""Tests for the target diff / change detection service."""

from app.services.mission.target_diff import (
    compare_missions,
    generate_diff_report,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mission(
    *,
    services=None,
    findings=None,
    vulns=None,
    mission_id="m1",
    target="10.0.0.1",
):
    """Helper to build a mission dict matching the shapes used by target_diff."""
    return {
        "id": mission_id,
        "target": target,
        "status": "completed",
        "findings": findings or [],
        "attack_surface": {
            "services": services or [],
            "vulnerabilities": vulns or [],
        },
        "summary": {},
    }


# ---------------------------------------------------------------------------
# compare_missions
# ---------------------------------------------------------------------------


class TestCompareMissions:
    """Tests for compare_missions."""

    def test_identical_missions_produce_empty_diff(self):
        svc = {"host": "10.0.0.1", "port": 80, "service": "http"}
        finding = {"name": "open-port", "host": "10.0.0.1", "port": 80}
        vuln = {"id": "vuln-1", "title": "XSS", "severity": "high"}

        m = _make_mission(services=[svc], findings=[finding], vulns=[vuln])
        diff = compare_missions(m, m)

        assert diff["new_services"] == []
        assert diff["removed_services"] == []
        assert diff["new_findings"] == []
        assert diff["resolved_findings"] == []
        assert diff["new_vulns"] == []
        assert diff["patched_vulns"] == []

    def test_new_services_detected(self):
        old = _make_mission(
            services=[
                {"host": "10.0.0.1", "port": 22, "service": "ssh"},
            ]
        )
        new = _make_mission(
            services=[
                {"host": "10.0.0.1", "port": 22, "service": "ssh"},
                {"host": "10.0.0.1", "port": 80, "service": "http"},
            ]
        )
        diff = compare_missions(old, new)

        assert len(diff["new_services"]) == 1
        assert diff["new_services"][0]["port"] == 80
        assert diff["removed_services"] == []

    def test_removed_services_detected(self):
        old = _make_mission(
            services=[
                {"host": "10.0.0.1", "port": 22, "service": "ssh"},
                {"host": "10.0.0.1", "port": 80, "service": "http"},
            ]
        )
        new = _make_mission(
            services=[
                {"host": "10.0.0.1", "port": 22, "service": "ssh"},
            ]
        )
        diff = compare_missions(old, new)

        assert diff["new_services"] == []
        assert len(diff["removed_services"]) == 1
        assert diff["removed_services"][0]["port"] == 80

    def test_new_findings_detected(self):
        old = _make_mission(findings=[])
        new = _make_mission(
            findings=[
                {"name": "sqli", "host": "10.0.0.1", "port": 80},
            ]
        )
        diff = compare_missions(old, new)

        assert len(diff["new_findings"]) == 1
        assert diff["resolved_findings"] == []

    def test_resolved_findings_detected(self):
        old = _make_mission(
            findings=[
                {"name": "sqli", "host": "10.0.0.1", "port": 80},
            ]
        )
        new = _make_mission(findings=[])
        diff = compare_missions(old, new)

        assert diff["new_findings"] == []
        assert len(diff["resolved_findings"]) == 1

    def test_new_vulns_detected(self):
        old = _make_mission(vulns=[])
        new = _make_mission(
            vulns=[
                {"id": "vuln-1", "title": "XSS", "severity": "high"},
            ]
        )
        diff = compare_missions(old, new)

        assert len(diff["new_vulns"]) == 1
        assert diff["patched_vulns"] == []

    def test_patched_vulns_detected(self):
        old = _make_mission(
            vulns=[
                {"id": "vuln-1", "title": "XSS", "severity": "high"},
            ]
        )
        new = _make_mission(vulns=[])
        diff = compare_missions(old, new)

        assert diff["new_vulns"] == []
        assert len(diff["patched_vulns"]) == 1

    def test_empty_missions(self):
        diff = compare_missions({}, {})
        assert diff["new_services"] == []
        assert diff["removed_services"] == []
        assert diff["new_findings"] == []
        assert diff["resolved_findings"] == []
        assert diff["new_vulns"] == []
        assert diff["patched_vulns"] == []

    def test_complex_diff(self):
        old = _make_mission(
            services=[
                {"host": "10.0.0.1", "port": 22, "service": "ssh"},
                {"host": "10.0.0.1", "port": 3306, "service": "mysql"},
            ],
            findings=[
                {"name": "weak-password", "host": "10.0.0.1", "port": 22},
                {"name": "anon-ftp", "host": "10.0.0.1", "port": 21},
            ],
            vulns=[
                {"id": "v1", "title": "Old vuln", "severity": "low"},
            ],
        )
        new = _make_mission(
            services=[
                {"host": "10.0.0.1", "port": 22, "service": "ssh"},
                {"host": "10.0.0.1", "port": 80, "service": "http"},
            ],
            findings=[
                {"name": "weak-password", "host": "10.0.0.1", "port": 22},
                {"name": "sqli", "host": "10.0.0.1", "port": 80},
            ],
            vulns=[
                {"id": "v2", "title": "New vuln", "severity": "critical"},
            ],
        )
        diff = compare_missions(old, new)

        assert len(diff["new_services"]) == 1
        assert diff["new_services"][0]["port"] == 80
        assert len(diff["removed_services"]) == 1
        assert diff["removed_services"][0]["port"] == 3306
        assert len(diff["new_findings"]) == 1
        assert diff["new_findings"][0]["name"] == "sqli"
        assert len(diff["resolved_findings"]) == 1
        assert diff["resolved_findings"][0]["name"] == "anon-ftp"
        assert len(diff["new_vulns"]) == 1
        assert len(diff["patched_vulns"]) == 1

    def test_findings_from_summary_fallback(self):
        old = {"summary": {"findings": [{"name": "a", "host": "h", "port": 1}]}}
        new = {"summary": {"findings": []}}
        diff = compare_missions(old, new)
        assert len(diff["resolved_findings"]) == 1


# ---------------------------------------------------------------------------
# generate_diff_report
# ---------------------------------------------------------------------------


class TestGenerateDiffReport:
    """Tests for generate_diff_report."""

    def test_report_contains_header(self):
        diff = compare_missions({}, {})
        report = generate_diff_report(diff)
        assert "# Mission Diff Report" in report

    def test_report_shows_new_services(self):
        diff = {
            "new_services": [{"host": "10.0.0.1", "port": 80, "service": "http"}],
            "removed_services": [],
            "new_findings": [],
            "resolved_findings": [],
            "new_vulns": [],
            "patched_vulns": [],
        }
        report = generate_diff_report(diff)
        assert "New Services (1)" in report
        assert "10.0.0.1:80" in report

    def test_report_shows_removed_services(self):
        diff = {
            "new_services": [],
            "removed_services": [{"host": "10.0.0.1", "port": 22, "service": "ssh"}],
            "new_findings": [],
            "resolved_findings": [],
            "new_vulns": [],
            "patched_vulns": [],
        }
        report = generate_diff_report(diff)
        assert "Removed Services (1)" in report
        assert "~~10.0.0.1:22~~" in report

    def test_report_shows_no_changes(self):
        diff = {
            "new_services": [],
            "removed_services": [],
            "new_findings": [],
            "resolved_findings": [],
            "new_vulns": [],
            "patched_vulns": [],
        }
        report = generate_diff_report(diff)
        assert "No service changes detected." in report
        assert "No finding changes detected." in report
        assert "No vulnerability changes detected." in report

    def test_report_shows_new_findings(self):
        diff = {
            "new_services": [],
            "removed_services": [],
            "new_findings": [{"name": "sqli", "host": "10.0.0.1", "severity": "high"}],
            "resolved_findings": [],
            "new_vulns": [],
            "patched_vulns": [],
        }
        report = generate_diff_report(diff)
        assert "New Findings (1)" in report
        assert "sqli" in report

    def test_report_shows_vulns(self):
        diff = {
            "new_services": [],
            "removed_services": [],
            "new_findings": [],
            "resolved_findings": [],
            "new_vulns": [{"id": "v1", "title": "XSS", "severity": "high", "cve_id": "CVE-2024-1234"}],
            "patched_vulns": [{"id": "v2", "title": "SQLi", "severity": "critical"}],
        }
        report = generate_diff_report(diff)
        assert "New Vulnerabilities (1)" in report
        assert "CVE-2024-1234" in report
        assert "Patched Vulnerabilities (1)" in report
        assert "~~SQLi~~" in report
