"""Tests for logout button correctness in base.html."""

from pathlib import Path

BASE_TEMPLATE = Path(__file__).resolve().parents[2] / "app" / "templates" / "base.html"


class TestLogoutButton:
    """Verify logout button in base.html works correctly."""

    def test_logout_uses_localstorage(self):
        """Logout must read token from localStorage, not document.cookie."""
        content = BASE_TEMPLATE.read_text()
        # Find the logout button section
        assert "localStorage.getItem('token')" in content or 'localStorage.getItem("token")' in content, \
            "Logout should read token from localStorage"

    def test_logout_does_not_read_cookie(self):
        """Logout must NOT try to read HttpOnly cookie via document.cookie.match."""
        content = BASE_TEMPLATE.read_text()
        # The old broken pattern
        assert "document.cookie.match(/access_token" not in content, \
            "Logout must not try to read HttpOnly cookie via document.cookie"

    def test_logout_uses_correct_api_path(self):
        """Logout must use /api/v1/auth/logout, not /api/auth/logout."""
        content = BASE_TEMPLATE.read_text()
        assert "/api/v1/auth/logout" in content, "Logout must use versioned API path"

    def test_logout_clears_localstorage(self):
        """Logout must clear token from localStorage."""
        content = BASE_TEMPLATE.read_text()
        assert "localStorage.removeItem('token')" in content or 'localStorage.removeItem("token")' in content, \
            "Logout must clear token from localStorage"
