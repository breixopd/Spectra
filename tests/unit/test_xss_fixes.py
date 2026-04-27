"""Tests for XSS prevention and escapeHtml consolidation."""

import re
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
DASHBOARD = TEMPLATES_DIR / "dashboard.html"
BASE = TEMPLATES_DIR / "base.html"
DASHBOARD_JS = Path(__file__).resolve().parents[2] / "static" / "js" / "pages" / "dashboard" / "init.js"

# Templates that previously had duplicate escapeHtml
PREVIOUSLY_DUPLICATED = [
    TEMPLATES_DIR / "manual_tools.html",
    TEMPLATES_DIR / "reports.html",
    TEMPLATES_DIR / "observability.html",
    TEMPLATES_DIR / "admin.html",
]


class TestEscapeHtmlConsolidation:
    """escapeHtml must be defined exactly once in base.html."""

    def test_base_defines_escape_html(self):
        content = BASE.read_text()
        matches = re.findall(r"function\s+escapeHtml\s*\(", content)
        assert len(matches) == 1, f"base.html must define escapeHtml exactly once, found {len(matches)}"

    def test_no_duplicates_in_templates(self):
        """Templates that extend base.html must NOT redefine escapeHtml."""
        for tmpl in PREVIOUSLY_DUPLICATED:
            if tmpl.exists():
                content = tmpl.read_text()
                matches = re.findall(r"function\s+escapeHtml\s*\(", content)
                assert len(matches) == 0, f"{tmpl.name} still has duplicate escapeHtml ({len(matches)} found)"

    def test_api_js_no_escape_html(self):
        api_js = Path(__file__).resolve().parents[2] / "static" / "js" / "api.js"
        content = api_js.read_text()
        assert not re.search(r"function\s+escapeHtml\s*\(", content), (
            "api.js must not define escapeHtml (consolidated in base.html)"
        )


class TestDashboardXssFix:
    """Dashboard task tree must not use inline onclick with JSON.stringify."""

    def test_no_inline_onclick_json(self):
        content = DASHBOARD.read_text()
        assert "onclick='openFindingDetail(${JSON.stringify" not in content, (
            "Dashboard must not use inline onclick with JSON.stringify (XSS risk)"
        )

    def test_uses_data_attribute(self):
        content = DASHBOARD_JS.read_text()
        assert "data-task-id" in content, "Dashboard task tree must use data attributes for task identification"

    def test_uses_event_delegation(self):
        content = DASHBOARD_JS.read_text()
        assert "task-tree-content" in content and (
            "addEventListener('click'" in content or 'addEventListener("click"' in content
        ), "Dashboard must use event delegation for task tree clicks"
