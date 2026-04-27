"""
Tests for the security module (JWT and password hashing).
"""

from datetime import timedelta

import jwt
import pytest

from app.auth.security import (
    JWTError,
    create_access_token,
    decode_token,
    get_password_hash,
    verify_password,
)
from app.core.config import settings


class TestPasswordHashing:
    """Tests for password hashing functions."""

    def test_get_password_hash_returns_hash(self):
        """get_password_hash should return a bcrypt hash."""
        password = "mysecretpassword"
        hashed = get_password_hash(password)

        assert hashed != password
        assert hashed.startswith("$2")  # bcrypt prefix
        assert len(hashed) == 60  # bcrypt hash length

    def test_get_password_hash_different_for_same_password(self):
        """get_password_hash should generate different hashes (different salts)."""
        password = "samepassword"
        hash1 = get_password_hash(password)
        hash2 = get_password_hash(password)

        assert hash1 != hash2  # Different salts

    def test_get_password_hash_raises_on_empty(self):
        """get_password_hash should raise ValueError for empty password."""
        with pytest.raises(ValueError, match="Password cannot be empty"):
            get_password_hash("")

    def test_get_password_hash_handles_unicode(self):
        """get_password_hash should handle unicode passwords."""
        password = "пароль日本語🔐"
        hashed = get_password_hash(password)

        assert hashed is not None
        assert verify_password(password, hashed)

    def test_verify_password_correct(self):
        """verify_password should return True for correct password."""
        password = "correctpassword"
        hashed = get_password_hash(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """verify_password should return False for incorrect password."""
        password = "correctpassword"
        hashed = get_password_hash(password)

        assert verify_password("wrongpassword", hashed) is False

    def test_verify_password_empty_plain(self):
        """verify_password should return False for empty plain password."""
        hashed = get_password_hash("somepassword")

        assert verify_password("", hashed) is False

    def test_verify_password_empty_hash(self):
        """verify_password should return False for empty hash."""
        assert verify_password("somepassword", "") is False

    def test_verify_password_invalid_hash(self):
        """verify_password should return False for invalid hash format."""
        assert verify_password("password", "notavalidhash") is False

    def test_bcrypt_72_byte_limit(self):
        """Passwords longer than 72 bytes should still work (truncated)."""
        # Create a password longer than 72 bytes
        long_password = "a" * 100
        hashed = get_password_hash(long_password)

        # Should still verify
        assert verify_password(long_password, hashed) is True

        # The first 72 bytes should also verify (bcrypt truncates)
        assert verify_password(long_password[:72], hashed) is True


class TestJWTTokens:
    """Tests for JWT token functions."""

    def test_create_access_token_basic(self):
        """create_access_token should create a valid JWT."""
        data = {"sub": "user@example.com"}
        token = create_access_token(data)

        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 50  # JWTs are typically longer

    def test_create_access_token_requires_sub(self):
        """create_access_token should require 'sub' claim."""
        with pytest.raises(ValueError, match="must have a 'sub' claim"):
            create_access_token({"email": "user@example.com"})

    @pytest.mark.asyncio
    async def test_create_access_token_preserves_claims(self):
        """create_access_token should preserve additional claims."""
        data = {"sub": "user123", "role": "admin", "permissions": ["read", "write"]}
        token = create_access_token(data)
        decoded = await decode_token(token)

        assert decoded["sub"] == "user123"
        assert decoded["role"] == "admin"
        assert decoded["permissions"] == ["read", "write"]

    @pytest.mark.asyncio
    async def test_create_access_token_adds_exp_and_iat(self):
        """create_access_token should add exp and iat claims."""
        token = create_access_token({"sub": "user"})
        decoded = await decode_token(token)

        assert "exp" in decoded
        assert "iat" in decoded
        assert decoded["exp"] > decoded["iat"]

    @pytest.mark.asyncio
    async def test_create_access_token_custom_expiry(self):
        """create_access_token should respect custom expiry."""
        # Create token with 1 minute expiry
        token = create_access_token({"sub": "user"}, expires_delta=timedelta(minutes=1))
        decoded = await decode_token(token)

        # exp - iat should be approximately 60 seconds
        assert (decoded["exp"] - decoded["iat"]) == 60

    @pytest.mark.asyncio
    async def test_decode_token_valid(self):
        """decode_token should decode a valid token."""
        original_data = {"sub": "testuser", "custom": "value"}
        token = create_access_token(original_data)

        decoded = await decode_token(token)

        assert decoded["sub"] == "testuser"
        assert decoded["custom"] == "value"

    @pytest.mark.asyncio
    async def test_decode_token_invalid_signature(self):
        """decode_token should raise JWTError for invalid signature."""
        # Create a token with a different secret
        token = jwt.encode(
            {"sub": "user", "exp": 9999999999},
            "wrong-secret-used-for-invalid-signature-tests",
            algorithm=settings.JWT_ALGORITHM,
        )

        with pytest.raises(JWTError):
            await decode_token(token)

    @pytest.mark.asyncio
    async def test_decode_token_expired(self):
        """decode_token should raise JWTError for expired token."""
        # Create an already-expired token
        token = create_access_token(
            {"sub": "user"},
            expires_delta=timedelta(seconds=-10),  # Expired 10 seconds ago
        )

        with pytest.raises(JWTError):
            await decode_token(token)

    @pytest.mark.asyncio
    async def test_decode_token_malformed(self):
        """decode_token should raise JWTError for malformed token."""
        with pytest.raises(JWTError):
            await decode_token("not.a.valid.jwt.token")

    def test_token_does_not_contain_original_dict(self):
        """Token should not modify the original data dict."""
        original = {"sub": "user"}
        create_access_token(original)

        # Original should not have exp/iat added
        assert "exp" not in original
        assert "iat" not in original


class TestSecurityIntegration:
    """Integration tests for security functions."""

    @pytest.mark.asyncio
    async def test_full_auth_flow(self):
        """Test complete authentication flow."""
        # Register: hash password
        password = "SecureP@ssw0rd!"
        hashed = get_password_hash(password)

        # Login: verify password
        assert verify_password(password, hashed)

        # Create token
        token = create_access_token({"sub": "user@example.com", "user_id": 123})

        # Verify token
        decoded = await decode_token(token)
        assert decoded["sub"] == "user@example.com"
        assert decoded["user_id"] == 123

    def test_wrong_password_fails_auth(self):
        """Wrong password should fail authentication."""
        password = "correctpassword"
        hashed = get_password_hash(password)

        # Wrong password should fail
        assert not verify_password("wrongpassword", hashed)
