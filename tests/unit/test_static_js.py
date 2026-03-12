"""Tests for static JS file conventions — verifies api.js utilities and fetch usage."""

import re
from pathlib import Path

import pytest

STATIC_JS_DIR = Path(__file__).resolve().parents[2] / "app" / "static" / "js"
API_JS = STATIC_JS_DIR / "api.js"

# JS files that consume the API (exclude api.js itself and data-only helpers)
CONSUMER_JS_FILES = [f for f in sorted(STATIC_JS_DIR.glob("*.js")) if f.name not in ("api.js", "helper_data.js")]


class TestApiJsUtilities:
    def test_api_js_exists(self):
        assert API_JS.exists(), "app/static/js/api.js must exist"

    def test_debounce_function_defined(self):
        content = API_JS.read_text()
        assert re.search(r"function\s+debounce\s*\(", content), "api.js must define a debounce function"

    def test_escape_html_function_defined(self):
        content = API_JS.read_text()
        assert re.search(r"function\s+escapeHtml\s*\(", content), "api.js must define an escapeHtml function"

    def test_spectra_api_object_defined(self):
        content = API_JS.read_text()
        assert "spectraApi" in content, "api.js must define the spectraApi object"


class TestJsUsesSpectraApi:
    """All consumer JS files should use spectraApi, not raw fetch."""

    @pytest.mark.parametrize("js_file", CONSUMER_JS_FILES, ids=lambda p: p.name)
    def test_no_raw_fetch_calls(self, js_file: Path):
        content = js_file.read_text()
        # Skip files that don't make any network calls
        if "spectraApi" not in content and "fetch(" not in content:
            pytest.skip(f"{js_file.name} makes no API calls")
        raw_fetches = re.findall(r"(?<!\.)\bfetch\s*\(", content)
        assert not raw_fetches, (
            f"{js_file.name} uses raw fetch() instead of spectraApi ({len(raw_fetches)} occurrence(s))"
        )
