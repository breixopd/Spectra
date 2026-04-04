"""
Security utilities for JWT authentication and password hashing.

Provides secure password hashing using bcrypt and JWT token generation/validation.
Follows OWASP security best practices.
"""

import asyncio
import base64
import hashlib
import json
import logging
import threading
import time as _time
from datetime import UTC, datetime, timedelta

UTC = UTC
from typing import Any

import bcrypt
import jwt
import pyotp
from cryptography.fernet import Fernet, InvalidToken
from jwt.exceptions import InvalidTokenError as JWTError

from app.core.config import settings
from app.core.constants import JWT_BLACKLIST_MAX_SIZE

__all__ = [
    "create_access_token",
    "create_refresh_token",
    "create_password_reset_token",
    "verify_password_reset_token",
    "create_email_verification_token",
    "verify_email_verification_token",
    "decode_token",
    "verify_password",
    "get_password_hash",
    "invalidate_token",
    "is_token_blacklisted",
    "invalidate_all_user_tokens",
    "encrypt_mfa_secret",
    "decrypt_mfa_secret",
    "encrypt_byok_key",
    "decrypt_byok_key",
    "verify_totp",
    "JWTError",
]

_logger = logging.getLogger(__name__)

# --- Persistent Token Blacklist ---

# In-memory caches loaded from DB on startup
_blacklisted_tokens: dict[str, float] = {}  # token_hash -> expiry timestamp
_user_token_blacklist: dict[str, float] = {}  # username -> invalidated_before timestamp
_blacklist_lock = threading.Lock()
_blacklist_loaded = False


def _ensure_blacklist_loaded() -> None:
    """Schedule a one-time DB load; flag is only set inside the coroutine itself."""
    global _blacklist_loaded
    if _blacklist_loaded:
        return
    with _blacklist_lock:
        if _blacklist_loaded:
            return
        # Mark loaded *before* scheduling so concurrent callers don't also
        # schedule, but the coroutine will reset it on failure.
        _blacklist_loaded = True
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_load_from_db())
        except RuntimeError:
            # Not in an async context; will be retried on next request.
            _blacklist_loaded = False


def _persist_blacklist() -> None:
    """Persist blacklist to DB."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_persist_to_db())
    except RuntimeError:
        pass


async def _persist_to_db() -> None:
    """Persist blacklist state to database via cache_entries table."""
    try:
        from sqlalchemy import text

        from app.core.database import async_session_maker

        now = _time.time()
        async with async_session_maker() as session:
            for token_hash, expiry in _blacklisted_tokens.items():
                if expiry > now:
                    await session.execute(
                        text(
                            "INSERT INTO cache_entries (key, value, expires_at, created_at) "
                            "VALUES (:key, :value, :expires_at, :created_at) "
                            "ON CONFLICT (key) DO UPDATE SET value = :value, expires_at = :expires_at"
                        ),
                        {
                            "key": f"blacklist:token:{token_hash}",
                            "value": json.dumps({"type": "token", "expiry": expiry}),
                            "expires_at": datetime.fromtimestamp(expiry, tz=UTC),
                            "created_at": datetime.now(UTC),
                        },
                    )

            for username, invalidated_before in _user_token_blacklist.items():
                await session.execute(
                    text(
                        "INSERT INTO cache_entries (key, value, expires_at, created_at) "
                        "VALUES (:key, :value, NULL, :created_at) "
                        "ON CONFLICT (key) DO UPDATE SET value = :value"
                    ),
                    {
                        "key": f"blacklist:user:{username}",
                        "value": json.dumps({"type": "user", "invalidated_before": invalidated_before}),
                        "created_at": datetime.now(UTC),
                    },
                )

            await session.commit()
    except (OSError, RuntimeError) as e:
        _logger.warning("Failed to persist blacklist to DB: %s", e)


async def _load_from_db() -> None:
    """Load blacklist state from database, overlaying in-memory cache."""
    try:
        from sqlalchemy import text

        from app.core.database import async_session_maker

        async with async_session_maker() as session:
            rows = (
                (await session.execute(text("SELECT key, value FROM cache_entries WHERE key LIKE 'blacklist:%'")))
                .mappings()
                .all()
            )

        now = _time.time()
        loaded_tokens = 0
        loaded_users = 0
        with _blacklist_lock:
            for row in rows:
                data = json.loads(row["value"])
                key: str = row["key"]
                if key.startswith("blacklist:token:"):
                    token_hash = key[len("blacklist:token:") :]
                    expiry = data.get("expiry", 0)
                    if expiry > now:
                        _blacklisted_tokens[token_hash] = expiry
                        loaded_tokens += 1
                elif key.startswith("blacklist:user:"):
                    username = key[len("blacklist:user:") :]
                    _user_token_blacklist[username] = data.get("invalidated_before", 0)
                    loaded_users += 1

        _logger.info("Loaded %d token + %d user blacklist entries from DB", loaded_tokens, loaded_users)
    except (OSError, RuntimeError) as e:
        _logger.warning("Failed to load blacklist from DB: %s", e)


def _token_hash(token: str) -> str:
    """Create a SHA-256 hash of the token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def _get_token_expiry(token: str) -> float:
    """Extract expiry timestamp from a JWT token, default to 1h from now."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY.get_secret_value(),
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_exp": False},
        )
        return float(payload.get("exp", _time.time() + 3600))
    except (ValueError, TypeError, KeyError):
        return _time.time() + 3600


def invalidate_token(token: str) -> None:
    """Add a token to the blacklist and persist."""
    _ensure_blacklist_loaded()
    expiry = _get_token_expiry(token)
    with _blacklist_lock:
        if len(_blacklisted_tokens) >= JWT_BLACKLIST_MAX_SIZE:
            _cleanup_expired()
        _blacklisted_tokens[_token_hash(token)] = expiry
        _persist_blacklist()


_cleanup_counter = 0


def _cleanup_expired() -> None:
    """Remove expired entries from the in-memory blacklist."""
    now = _time.time()
    expired = [h for h, exp in _blacklisted_tokens.items() if exp <= now]
    for h in expired:
        del _blacklisted_tokens[h]


def is_token_blacklisted(token: str) -> bool:
    """Check if a token is blacklisted (by direct blacklist or user-level invalidation)."""
    _ensure_blacklist_loaded()
    with _blacklist_lock:
        global _cleanup_counter
        _cleanup_counter += 1
        if _cleanup_counter >= 100:
            _cleanup_counter = 0
            _cleanup_expired()
    token_h = _token_hash(token)
    with _blacklist_lock:
        exp = _blacklisted_tokens.get(token_h)
        if exp is not None and exp > _time.time():
            return True
    # Check user-level invalidation
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY.get_secret_value(),
            algorithms=[settings.JWT_ALGORITHM],
        )
        username = payload.get("sub")
        iat = payload.get("iat")
        if username and iat:
            with _blacklist_lock:
                invalidated_before = _user_token_blacklist.get(username)
            if invalidated_before and iat < invalidated_before:
                return True
    except JWTError:
        pass
    return False


def invalidate_all_user_tokens(username: str) -> None:
    """Invalidate all tokens for a user by recording current timestamp.

    Uses int(time) + 1 to account for JWT iat being stored as integer seconds.
    """
    _ensure_blacklist_loaded()
    now = int(datetime.now(UTC).timestamp()) + 1
    with _blacklist_lock:
        _user_token_blacklist[username] = now
        _persist_blacklist()


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

    now = datetime.now(UTC)
    expire = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))

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

    now = datetime.now(UTC)
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


def create_password_reset_token(user_id: str, expires_minutes: int = 30) -> str:
    """Create a time-limited password reset JWT."""
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=expires_minutes)
    return jwt.encode(
        {"sub": user_id, "type": "password_reset", "exp": expire, "iat": now},
        settings.JWT_SECRET_KEY.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )


def verify_password_reset_token(token: str) -> str | None:
    """Verify a password reset token, return user_id or None."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY.get_secret_value(),
            algorithms=[settings.JWT_ALGORITHM],
        )
        if payload.get("type") != "password_reset":
            return None
        return payload.get("sub")
    except JWTError:
        return None


def create_email_verification_token(user_id: str) -> str:
    """Create a short-lived email verification token (24h expiry)."""
    now = datetime.now(UTC)
    expire = now + timedelta(hours=24)
    return jwt.encode(
        {"sub": user_id, "type": "email_verify", "exp": expire, "iat": now},
        settings.JWT_SECRET_KEY.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )


def verify_email_verification_token(token: str) -> str | None:
    """Verify an email verification token. Returns user_id or None."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY.get_secret_value(),
            algorithms=[settings.JWT_ALGORITHM],
        )
        if payload.get("type") != "email_verify":
            return None
        return payload.get("sub")
    except JWTError:
        return None


def decode_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT token.

    Args:
        token: The JWT token string to decode.

    Returns:
        The decoded token payload.

    Raises:
        JWTError: If the token is invalid, expired, or blacklisted.
    """
    if is_token_blacklisted(token):
        raise JWTError("Token has been revoked")

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


# --- MFA / TOTP Helpers ---


def _get_encryption_key() -> bytes:
    """Get the encryption key, separate from JWT signing.

    Uses ENCRYPTION_KEY when set, falling back to JWT_SECRET_KEY
    for backward compatibility with existing encrypted data.
    """
    key = settings.ENCRYPTION_KEY or settings.JWT_SECRET_KEY.get_secret_value()
    # Derive a proper Fernet key from the secret
    derived = hashlib.sha256(key.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(derived)


def _get_fernet() -> Fernet:
    """Derive a Fernet instance from the encryption key."""
    return Fernet(_get_encryption_key())


def encrypt_mfa_secret(secret: str) -> str:
    """Encrypt a TOTP secret for database storage."""
    return _get_fernet().encrypt(secret.encode("utf-8")).decode("utf-8")


def decrypt_mfa_secret(encrypted: str) -> str:
    """Decrypt a stored TOTP secret."""
    try:
        return _get_fernet().decrypt(encrypted.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise ValueError("Failed to decrypt MFA secret")


def encrypt_byok_key(key: str) -> str:
    """Encrypt a BYOK API key for storage."""
    return _get_fernet().encrypt(key.encode("utf-8")).decode("utf-8")


def decrypt_byok_key(encrypted: str) -> str:
    """Decrypt a stored BYOK API key."""
    try:
        return _get_fernet().decrypt(encrypted.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise ValueError("Failed to decrypt BYOK key")


def verify_totp(secret: str, code: str) -> bool:
    """Verify a TOTP code against a secret with 1-step tolerance."""
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)
