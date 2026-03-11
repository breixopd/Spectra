"""Tests for password validation logic."""

import pytest


def _validate(password: str) -> str:
    """Import and call the shared password validator."""
    from app.api.routers.public import _validate_password_strength
    return _validate_password_strength(password)


class TestPasswordValidation:
    """Test password strength validation rules."""

    def test_valid_password(self):
        result = _validate("Str0ngPass")
        assert result == "Str0ngPass"

    def test_valid_password_with_symbols(self):
        result = _validate("C0mpl3x!@#")
        assert result == "C0mpl3x!@#"

    def test_too_short(self):
        with pytest.raises(ValueError, match="at least 8 characters"):
            _validate("Ab1")

    def test_exactly_seven_chars(self):
        with pytest.raises(ValueError, match="at least 8 characters"):
            _validate("Abcde1x")

    def test_exactly_eight_chars_valid(self):
        result = _validate("Abcdef1x")
        assert result == "Abcdef1x"

    def test_no_uppercase(self):
        with pytest.raises(ValueError, match="uppercase"):
            _validate("alllower1")

    def test_no_lowercase(self):
        with pytest.raises(ValueError, match="lowercase"):
            _validate("ALLUPPER1")

    def test_no_digit(self):
        with pytest.raises(ValueError, match="digit"):
            _validate("NoDigitHere")

    def test_all_digits(self):
        with pytest.raises(ValueError, match="uppercase"):
            _validate("12345678")

    def test_all_spaces(self):
        with pytest.raises(ValueError, match="uppercase"):
            _validate("        ")

    def test_long_valid_password(self):
        pw = "A" + "b" * 50 + "1"
        result = _validate(pw)
        assert result == pw

    def test_unicode_characters(self):
        """Unicode letters count as letters for upper/lower checks."""
        result = _validate("Ünïcödé1A")
        assert result == "Ünïcödé1A"
