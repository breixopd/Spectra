"""Tests for logout button correctness in base.html."""

from pathlib import Path

BASE_TEMPLATE = Path(__file__).resolve().parents[3] / "app" / "templates" / "base.html"


class TestLogoutButton:
    """Verify logout button in base.html matches the current cookie-backed auth flow."""

    def test_logout_posts_to_versioned_api(self):
        content = BASE_TEMPLATE.read_text()
        assert "/api/v1/auth/logout" in content
        assert "/api/v1/auth/logout" in content
        assert "fetch('/api/v1/auth/logout'" in content

    def test_logout_uses_spectra_api_client(self):
        """spectraApi handles credentials and CSRF automatically."""
        content = BASE_TEMPLATE.read_text()
        assert "/api/v1/auth/logout" in content
        assert "fetch('/api/v1/auth/logout'" in content

    def test_logout_does_not_read_cookie_manually(self):
        content = BASE_TEMPLATE.read_text()
        assert "document.cookie.match(/access_token" not in content

    def test_logout_does_not_use_localstorage_token(self):
        content = BASE_TEMPLATE.read_text()
        assert "localStorage.getItem" not in content
        assert "access_token" not in content
