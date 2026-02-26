"""
Security utilities for JWT authentication and password hashing.

Provides secure password hashing using bcrypt and JWT token generation/validation.
Follows OWASP security best practices.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings

__all__ = [
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "verify_password",
    "get_password_hash",
    "JWTError",
]


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """
    Create a JWT access token.

    Args:
        data: Claims dictionary containing at least 'sub' (subject).
        expires_delta: Custom expiration time. Defaults to settings value.

    Returns:
        Encoded JWT token string.

    Raises:
        ValueError: If 'sub' claim is missing from data.
    """
    if "sub" not in data:
        raise ValueError("Token must have a 'sub' claim")

    to_encode = data.copy()

    now = datetime.now(timezone.utc)
    expire = now + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    to_encode.update(
        {
            "exp": expire,
            "iat": now,
            "type": "access",
        }
    )

    return jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )


def create_refresh_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """
    Create a JWT refresh token.

    Args:
        data: Claims dictionary containing at least 'sub' (subject).
        expires_delta: Custom expiration time. Defaults to 7 days.

    Returns:
        Encoded JWT token string.
    """
    if "sub" not in data:
        raise ValueError("Token must have a 'sub' claim")

    to_encode = data.copy()

    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(days=7))

    to_encode.update(
        {
            "exp": expire,
            "iat": now,
            "type": "refresh",
        }
    )

    return jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT token.

    Args:
        token: The JWT token string to decode.

    Returns:
        The decoded token payload.

    Raises:
        JWTError: If the token is invalid or expired.
    """
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY.get_secret_value(),
        algorithms=[settings.JWT_ALGORITHM],
    )


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against a hash.

    Args:
        plain_password: The plaintext password to verify.
        hashed_password: The bcrypt hash to verify against.

    Returns:
        True if the password matches, False otherwise.
    """
    if not plain_password or not hashed_password:
        return False

    # Encode to bytes and truncate to 72 bytes for bcrypt compatibility
    password_bytes = plain_password.encode("utf-8")[:72]
    hashed_bytes = hashed_password.encode("utf-8")

    try:
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except (ValueError, TypeError):
        return False


def get_password_hash(password: str) -> str:
    """
    Hash a password using bcrypt.

    Args:
        password: The plaintext password to hash.

    Returns:
        The bcrypt hash string.

    Raises:
        ValueError: If password is empty.
    """
    if not password:
        raise ValueError("Password cannot be empty")

    # Encode to bytes and truncate to 72 bytes for bcrypt compatibility
    password_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt(rounds=12)  # Increased from default 10 for better security
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")
