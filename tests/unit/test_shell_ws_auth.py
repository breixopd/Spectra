"""Tests for shell WebSocket authentication in templates."""

from pathlib import Path

SHELL_TEMPLATE = Path(__file__).resolve().parents[2] / "app" / "templates" / "shell.html"
TARGETS_JS = Path(__file__).resolve().parents[2] / "app" / "static" / "js" / "targets.js"


class TestShellWebSocketAuth:
    """Shell WebSocket connections must include auth tokens."""

    def test_shell_template_passes_token(self):
        """shell.html must include token in WebSocket URL."""
        content = SHELL_TEMPLATE.read_text()
        assert "token=" in content or "token'" in content, \
            "shell.html must pass auth token in WebSocket URL"

    def test_shell_template_reads_token(self):
        """shell.html must read token from localStorage."""
        content = SHELL_TEMPLATE.read_text()
        assert "localStorage.getItem" in content, \
            "shell.html must read auth token from localStorage"

    def test_targets_js_passes_token(self):
        """targets.js must include token in shell WebSocket URL."""
        content = TARGETS_JS.read_text()
        assert "token=" in content or "token'" in content, \
            "targets.js must pass auth token in shell WebSocket URL"

    def test_targets_js_reads_token(self):
        """targets.js must read token from localStorage."""
        content = TARGETS_JS.read_text()
        assert "localStorage.getItem" in content, \
            "targets.js must read auth token from localStorage"

    def test_shell_template_encodes_token(self):
        """shell.html must URL-encode the token with encodeURIComponent."""
        content = SHELL_TEMPLATE.read_text()
        assert "encodeURIComponent" in content, \
            "shell.html must URL-encode auth token with encodeURIComponent"

    def test_targets_js_encodes_token(self):
        """targets.js must URL-encode the token with encodeURIComponent."""
        content = TARGETS_JS.read_text()
        assert "encodeURIComponent" in content, \
            "targets.js must URL-encode auth token with encodeURIComponent"
