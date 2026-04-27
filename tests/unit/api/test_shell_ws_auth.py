"""Tests for token-free shell WebSocket connections in templates."""

from pathlib import Path

SHELL_TEMPLATE = Path(__file__).resolve().parents[3] / "templates" / "shell.html"
TARGETS_JS = Path(__file__).resolve().parents[3] / "static" / "js" / "pages" / "targets" / "shell.js"


class TestShellWebSocketAuth:
    """Shell WebSocket connections should use the session path directly, without query-token auth."""

    def test_shell_template_uses_session_path(self):
        content = SHELL_TEMPLATE.read_text()
        assert "/api/v1/shell/${sessionId}" in content
        assert "new ReconnectingWebSocket(wsUrl" in content

    def test_shell_template_does_not_read_local_storage_token(self):
        content = SHELL_TEMPLATE.read_text()
        assert "localStorage.getItem" not in content
        assert "token=" not in content
        assert "encodeURIComponent" not in content

    def test_targets_js_uses_session_path(self):
        content = TARGETS_JS.read_text()
        assert "/api/v1/shell/${sessionId}" in content
        assert "new ReconnectingWebSocket(wsUrl" in content

    def test_targets_js_does_not_read_local_storage_token(self):
        content = TARGETS_JS.read_text()
        assert "localStorage.getItem" not in content
        assert "token=" not in content
        assert "encodeURIComponent" not in content
