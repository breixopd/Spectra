"""Tests for MFA login UI flow in login.html template."""

from pathlib import Path

import pytest

LOGIN_TEMPLATE = Path(__file__).resolve().parents[2] / "app" / "templates" / "login.html"


class TestMfaLoginStep:
    """Verify login.html has a working MFA TOTP step."""

    def test_template_exists(self):
        assert LOGIN_TEMPLATE.exists()

    def test_mfa_step_element_present(self):
        content = LOGIN_TEMPLATE.read_text()
        assert 'id="mfa-step"' in content, "Login page must have MFA step element"

    def test_totp_input_present(self):
        content = LOGIN_TEMPLATE.read_text()
        assert 'id="totp-code"' in content, "Login page must have TOTP code input"

    def test_totp_input_has_numeric_mode(self):
        content = LOGIN_TEMPLATE.read_text()
        assert 'inputmode="numeric"' in content, "TOTP input must use numeric keyboard"

    def test_totp_input_maxlength(self):
        content = LOGIN_TEMPLATE.read_text()
        assert 'maxlength="6"' in content, "TOTP input must accept exactly 6 digits"

    def test_mfa_verify_endpoint_used(self):
        content = LOGIN_TEMPLATE.read_text()
        assert "/api/v1/auth/mfa/verify" in content, "Must call MFA verify endpoint"

    def test_mfa_token_not_stored_in_localstorage(self):
        """MFA temp token must NOT be stored in localStorage as 'token'."""
        content = LOGIN_TEMPLATE.read_text()
        # The MFA flow should use a variable, not localStorage
        # Check that mfa_required branch does NOT do localStorage.setItem('token', ...)
        # before MFA verification. The branch ends with 'return;'.
        lines = content.split("\n")
        in_mfa_branch = False
        for line in lines:
            if "mfa_required" in line:
                in_mfa_branch = True
            if in_mfa_branch and "return;" in line.strip():
                # mfa_required branch exits here; subsequent code is the non-MFA path
                break
            if in_mfa_branch and "localStorage.setItem" in line and "'token'" in line:
                pytest.fail("MFA temp token must not be stored in localStorage before verification")

    def test_mfa_cancel_button_present(self):
        content = LOGIN_TEMPLATE.read_text()
        assert "mfa-cancel" in content, "MFA step must have a cancel/back button"

    def test_mfa_uses_bearer_auth(self):
        """MFA verify must send the temp token as Bearer auth header."""
        content = LOGIN_TEMPLATE.read_text()
        assert "Bearer" in content, "MFA verify must use Bearer auth header"

    def test_login_form_still_present(self):
        """Non-MFA login form must still exist."""
        content = LOGIN_TEMPLATE.read_text()
        assert 'id="login-form"' in content
        assert "/api/v1/auth/token" in content
