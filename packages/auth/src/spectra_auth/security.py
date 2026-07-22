"""
Security utilities for JWT authentication and password hashing.

Provides secure password hashing using bcrypt and JWT token generation/validation.
Follows OWASP security best practices.
"""

import asyncio
import hashlib
import json
import logging
import time as _time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import bcrypt
import jwt
import pyotp
from jwt.exceptions import InvalidTokenError as JWTError
from sqlalchemy.exc import SQLAlchemyError

from spectra_common.config import settings
from spectra_common.constants import JWT_BLACKLIST_MAX_SIZE

__all__ = [
    "JWTError",
    "create_access_token",
    "create_email_verification_token",
    "create_password_reset_token",
    "create_refresh_token",
    "create_unsubscribe_token",
    "decode_token",
    "decrypt_byok_key",
    "decrypt_mfa_secret",
    "encrypt_byok_key",
    "encrypt_mfa_secret",
    "get_password_hash",
    "invalidate_all_user_tokens",
    "invalidate_token",
    "is_token_blacklisted",
    "sync_blacklist_from_db",
    "verify_email_verification_token",
    "verify_password",
    "verify_password_reset_token",
    "verify_totp",
    "verify_unsubscribe_token",
]

_logger = logging.getLogger(__name__)


# --- JWT signing primitives (asymmetric EdDSA preferred, HS256 fallback) ---


def _has_asymmetric_keys() -> bool:
    """True when an Ed25519 signing keypair is configured."""
    return bool(settings.JWT_PRIVATE_KEY.get_secret_value() and settings.JWT_PUBLIC_KEY)


def jwt_algorithm() -> str:
    """Effective JWT algorithm: ``EdDSA`` when a keypair is present, else the configured one."""
    return "EdDSA" if _has_asymmetric_keys() else settings.JWT_ALGORITHM


def _jwt_encode(payload: dict[str, Any]) -> str:
    """Encode a JWT, signing with the Ed25519 private key when available."""
    if _has_asymmetric_keys():
        return jwt.encode(payload, settings.JWT_PRIVATE_KEY.get_secret_value(), algorithm="EdDSA")
    return jwt.encode(payload, settings.JWT_SECRET_KEY.get_secret_value(), algorithm=settings.JWT_ALGORITHM)


def _jwt_decode(token: str, **options: Any) -> dict[str, Any]:
    """Decode/verify a JWT, using the Ed25519 public key when available."""
    if _has_asymmetric_keys():
        return jwt.decode(token, settings.JWT_PUBLIC_KEY, algorithms=["EdDSA"], **options)
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY.get_secret_value(),
        algorithms=[settings.JWT_ALGORITHM],
        **options,
    )


# --- Persistent Token Blacklist ---

# In-memory caches loaded from DB on startup
_blacklisted_tokens: dict[str, float] = {}  # token_hash -> expiry timestamp
_user_token_blacklist: dict[str, float] = {}  # username -> invalidated_before timestamp
_blacklist_lock = asyncio.Lock()
_blacklist_ready = asyncio.Event()
_blacklist_load_started = False


async def _ensure_blacklist_loaded() -> None:
    """Load revocation state before accepting any JWT.

    A missing cache is not evidence that a token is valid.  On a cold replica,
    authentication therefore fails closed until the durable blacklist has been
    loaded successfully.
    """
    global _blacklist_load_started
    if _blacklist_ready.is_set():
        return
    need_load = False
    async with _blacklist_lock:
        if not _blacklist_ready.is_set() and not _blacklist_load_started:
            _blacklist_load_started = True
            need_load = True
    if need_load:
        await _load_from_db()
    elif not _blacklist_ready.is_set():
        try:
            await asyncio.wait_for(_blacklist_ready.wait(), timeout=10.0)
        except TimeoutError:
            _logger.warning("Blacklist DB load timed out; denying token validation")
    if not _blacklist_ready.is_set():
        raise JWTError("Token revocation state is unavailable")


async def _persist_blacklist_entry(
    key: str,
    value: dict[str, Any],
    *,
    expires_at: datetime | None,
) -> None:
    """Synchronously persist one revocation entry before reporting success."""
    try:
        from sqlalchemy import text

        from spectra_persistence.database import async_session_maker

        async with async_session_maker() as session:
            await session.execute(
                text(
                    "INSERT INTO cache_entries (key, value, expires_at, created_at) "
                    "VALUES (:key, :value, :expires_at, :created_at) "
                    "ON CONFLICT (key) DO UPDATE SET value = :value, expires_at = :expires_at"
                ),
                {
                    "key": key,
                    "value": json.dumps(value),
                    "expires_at": expires_at,
                    "created_at": datetime.now(UTC),
                },
            )
            await session.commit()
    except (OSError, RuntimeError, SQLAlchemyError) as exc:
        _logger.error("Failed to persist token revocation state: %s", exc)
        raise JWTError("Token revocation state is unavailable") from exc


async def _load_from_db() -> None:
    """Load blacklist state from database, overlaying in-memory cache."""
    global _blacklist_load_started
    try:
        from sqlalchemy import text

        from spectra_persistence.database import async_session_maker

        async with async_session_maker() as session:
            rows = (
                (await session.execute(text("SELECT key, value FROM cache_entries WHERE key LIKE 'blacklist:%'")))
                .mappings()
                .all()
            )

        now = _time.time()
        loaded_tokens = 0
        loaded_users = 0
        async with _blacklist_lock:
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

        _blacklist_ready.set()
        _logger.info("Loaded %d token + %d user blacklist entries from DB", loaded_tokens, loaded_users)
    except (OSError, RuntimeError, SQLAlchemyError, ValueError, TypeError, json.JSONDecodeError) as exc:
        _blacklist_load_started = False  # allow retry on next call
        _blacklist_ready.clear()
        _logger.warning("Failed to load blacklist from DB: %s", exc)


def _token_hash(token: str) -> str:
    """Create a SHA-256 hash of the token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def _get_token_expiry(token: str) -> float:
    """Extract expiry timestamp from a JWT token, default to 1h from now."""
    try:
        payload = _jwt_decode(token, options={"verify_exp": False})
        return float(payload.get("exp", _time.time() + 3600))
    except (JWTError, ValueError, TypeError, KeyError):
        return _time.time() + 3600


async def invalidate_token(token: str) -> None:
    """Durably revoke one token before returning to the caller."""
    await _ensure_blacklist_loaded()
    expiry = _get_token_expiry(token)
    token_h = _token_hash(token)
    async with _blacklist_lock:
        if len(_blacklisted_tokens) >= JWT_BLACKLIST_MAX_SIZE:
            _cleanup_expired()
        previous_expiry = _blacklisted_tokens.get(token_h)
        _blacklisted_tokens[token_h] = expiry
    try:
        await _persist_blacklist_entry(
            f"blacklist:token:{token_h}",
            {"type": "token", "expiry": expiry},
            expires_at=datetime.fromtimestamp(expiry, tz=UTC),
        )
    except JWTError:
        async with _blacklist_lock:
            if _blacklisted_tokens.get(token_h) == expiry:
                if previous_expiry is None:
                    _blacklisted_tokens.pop(token_h, None)
                else:
                    _blacklisted_tokens[token_h] = previous_expiry
        raise
    _notify_blacklist_change(f"token:{token_h}")


_cleanup_counter = 0


def _cleanup_expired() -> None:
    """Remove expired entries from the in-memory blacklist."""
    now = _time.time()
    expired = [h for h, exp in _blacklisted_tokens.items() if exp <= now]
    for h in expired:
        del _blacklisted_tokens[h]

    # Evict stale user-level blacklist entries older than max token lifetime + buffer
    max_lifetime_secs = (settings.ACCESS_TOKEN_EXPIRE_MINUTES + 60) * 60
    stale = [uid for uid, ts in _user_token_blacklist.items() if now - ts > max_lifetime_secs]
    for uid in stale:
        del _user_token_blacklist[uid]


async def is_token_blacklisted(token: str) -> bool:
    """Check if a token is blacklisted (by direct blacklist or user-level invalidation)."""
    await _ensure_blacklist_loaded()
    token_h = _token_hash(token)
    async with _blacklist_lock:
        global _cleanup_counter
        _cleanup_counter += 1
        if _cleanup_counter >= 100:
            _cleanup_counter = 0
            _cleanup_expired()
        exp = _blacklisted_tokens.get(token_h)
        if exp is not None and exp > _time.time():
            return True
    # Check user-level invalidation
    try:
        payload = _jwt_decode(token)
        username = payload.get("sub")
        iat = payload.get("iat")
        if username and iat:
            async with _blacklist_lock:
                invalidated_before = _user_token_blacklist.get(username)
            if invalidated_before and iat < invalidated_before:
                return True
    except JWTError:
        pass
    return False


async def invalidate_all_user_tokens(username: str) -> None:
    """Invalidate all tokens for a user by recording current timestamp.

    Uses int(time) + 1 to account for JWT iat being stored as integer seconds.
    """
    await _ensure_blacklist_loaded()
    now = int(datetime.now(UTC).timestamp()) + 1
    async with _blacklist_lock:
        previous_invalidation = _user_token_blacklist.get(username)
        _user_token_blacklist[username] = now
    try:
        await _persist_blacklist_entry(
            f"blacklist:user:{username}",
            {"type": "user", "invalidated_before": now},
            expires_at=None,
        )
    except JWTError:
        async with _blacklist_lock:
            if _user_token_blacklist.get(username) == now:
                if previous_invalidation is None:
                    _user_token_blacklist.pop(username, None)
                else:
                    _user_token_blacklist[username] = previous_invalidation
        raise
    _notify_blacklist_change(f"user:{username}")


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
            # JWT NumericDate claims have one-second precision.  A unique JTI
            # keeps rapid login/logout/login cycles from producing the same
            # token and accidentally revoking the newly issued token.
            "jti": uuid4().hex,
        }
    )

    return _jwt_encode(to_encode)


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
            "jti": uuid4().hex,
        }
    )

    return _jwt_encode(to_encode)


def create_password_reset_token(user_id: str, expires_minutes: int = 30) -> str:
    """Create a time-limited password reset JWT."""
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=expires_minutes)
    # Reset tokens are durable, one-time credentials.  A unique JTI prevents
    # two requests in the same clock second from producing the same token and
    # accidentally revoking a newly issued reset link when the first is used.
    return _jwt_encode({"sub": user_id, "type": "password_reset", "jti": str(uuid4()), "exp": expire, "iat": now})


def verify_password_reset_token(token: str) -> str | None:
    """Verify a password reset token, return user_id or None."""
    try:
        payload = _jwt_decode(token)
        if payload.get("type") != "password_reset":
            return None
        return payload.get("sub")
    except JWTError:
        return None


def create_email_verification_token(user_id: str) -> str:
    """Create a short-lived email verification token (24h expiry)."""
    now = datetime.now(UTC)
    expire = now + timedelta(hours=24)
    return _jwt_encode({"sub": user_id, "type": "email_verify", "exp": expire, "iat": now})


def verify_email_verification_token(token: str) -> str | None:
    """Verify an email verification token. Returns user_id or None."""
    try:
        payload = _jwt_decode(token)
        if payload.get("type") != "email_verify":
            return None
        return payload.get("sub")
    except JWTError:
        return None


def create_unsubscribe_token(user_id: str) -> str:
    """Create a long-lived unsubscribe token (90-day expiry)."""
    now = datetime.now(UTC)
    expire = now + timedelta(days=90)
    return _jwt_encode({"sub": user_id, "type": "unsubscribe", "exp": expire, "iat": now})


def verify_unsubscribe_token(token: str) -> str | None:
    """Verify an unsubscribe token. Returns user_id or None."""
    try:
        payload = _jwt_decode(token)
        if payload.get("type") != "unsubscribe":
            return None
        return payload.get("sub")
    except JWTError:
        return None


async def decode_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT token.

    Args:
        token: The JWT token string to decode.

    Returns:
        The decoded token payload.

    Raises:
        JWTError: If the token is invalid, expired, or blacklisted.
    """
    if await is_token_blacklisted(token):
        raise JWTError("Token has been revoked")

    return _jwt_decode(token)


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


# MFA/BYOK field encryption lives in the foundation layer (spectra_common.encryption);
# re-exported here for callers that import from spectra_auth.security.
from spectra_common.encryption import (
    decrypt_byok_key,
    decrypt_mfa_secret,
    encrypt_byok_key,
    encrypt_mfa_secret,
)


def verify_totp(secret: str, code: str) -> bool:
    """Verify a TOTP code against a secret with 1-step tolerance."""
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


# --- Cross-replica blacklist propagation ---


def _notify_blacklist_change(payload: str) -> None:
    """Send a PG NOTIFY so other replicas refresh their blacklist cache."""
    try:
        asyncio.get_running_loop()
        from spectra_common.tasks import create_safe_task

        create_safe_task(_send_blacklist_notify(payload), name="blacklist_notify")
    except RuntimeError:
        pass


async def _send_blacklist_notify(payload: str) -> None:
    """Execute pg_notify for blacklist changes."""
    try:
        from sqlalchemy import text

        from spectra_persistence.database import async_session_maker

        async with async_session_maker() as session:
            await session.execute(
                text("SELECT pg_notify('token_blacklist_changed', :payload)"),
                {"payload": payload},
            )
            await session.commit()
    except (OSError, RuntimeError) as e:
        _logger.warning("Failed to send blacklist NOTIFY: %s", e)


async def sync_blacklist_from_db() -> None:
    """Reload blacklist state from DB. Called by the PG LISTEN handler."""
    await _load_from_db()
