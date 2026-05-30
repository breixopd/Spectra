"""Shared helpers for auth sub-modules."""

import contextlib
import hashlib
import logging
import threading
import time
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_auth.security import (
    JWTError,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from spectra_common.config import settings
from spectra_persistence.models.user import User

logger = logging.getLogger(__name__)

# --- Constants ---
LOCKOUT_THRESHOLD_1 = 5
LOCKOUT_DURATION_1 = 300
LOCKOUT_THRESHOLD_2 = 10
LOCKOUT_DURATION_2 = 1800
ACCESS_COOKIE_KEY = "access_token"
REFRESH_COOKIE_KEY = "refresh_token"
ACCESS_COOKIE_PATH = "/"
REFRESH_COOKIE_PATH = "/api/v1/auth/refresh"
AUTH_COOKIE_SAMESITE = "lax"
REFRESH_TOKEN_MAX_AGE = 7 * 24 * 60 * 60
DUMMY_PASSWORD_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewKyNiLXCJzFhWMu"
_TOTP_REPLAY_WINDOW_SECONDS = 90
# In-memory fallback when Redis is unavailable (bounded to prevent memory exhaustion)
_TOTP_MAX_ENTRIES = 10000
_used_totp_codes: dict[str, float] = {}
_used_totp_codes_lock = threading.Lock()


def _get_redis_for_totp():
    """Return an async Redis client for TOTP replay tracking, or None."""
    try:
        import redis.asyncio as aioredis

        url = settings.RATE_LIMIT_STORAGE
        if url and url.startswith(("redis://", "rediss://")):
            return aioredis.from_url(url, socket_timeout=2)
    except Exception:
        logger.warning("Redis connection failed for TOTP replay tracking, falling back to in-memory", exc_info=True)
    return None


async def _consume_totp_code_async(user_id: str, code: str) -> bool:
    """Check TOTP replay via Redis. Falls back to in-memory if Redis is down."""
    code_hash = hashlib.sha256(f"{user_id}:{code}".encode()).hexdigest()
    redis_key = f"totp_used:{user_id}:{code_hash}"

    r = _get_redis_for_totp()
    if r is not None:
        try:
            existing = await r.set(redis_key, "1", nx=True, ex=_TOTP_REPLAY_WINDOW_SECONDS)
            await r.aclose()
            return existing is not None  # True if key was newly set (not a replay)
        except Exception:
            logger.warning("Redis TOTP replay check failed, falling back to in-memory", exc_info=True)
            with contextlib.suppress(Exception):
                await r.aclose()

    # In-memory fallback
    return _consume_totp_code(user_id, code)


def _consume_totp_code(user_id: str, code: str) -> bool:
    now = time.time()
    code_hash = hashlib.sha256(f"{user_id}:{code}".encode()).hexdigest()
    with _used_totp_codes_lock:
        expired = [key for key, expires_at in _used_totp_codes.items() if expires_at <= now]
        for key in expired:
            _used_totp_codes.pop(key, None)
        if code_hash in _used_totp_codes:
            return False
        # Evict oldest entries if at capacity
        if len(_used_totp_codes) >= _TOTP_MAX_ENTRIES:
            sorted_keys = sorted(_used_totp_codes, key=_used_totp_codes.get)
            for k in sorted_keys[: len(_used_totp_codes) - _TOTP_MAX_ENTRIES + 1]:
                _used_totp_codes.pop(k, None)
        _used_totp_codes[code_hash] = now + _TOTP_REPLAY_WINDOW_SECONDS
        return True


async def _check_lockout(user: User) -> None:
    """Raise 429 if the user account is currently locked."""
    if user.locked_until and user.locked_until > datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Account temporarily locked due to too many failed attempts",
        )


async def _record_failure(user: User, session: AsyncSession) -> None:
    """Record a failed login attempt and apply lockout if threshold reached."""
    user.login_fail_count = (user.login_fail_count or 0) + 1
    count = user.login_fail_count

    if count >= LOCKOUT_THRESHOLD_2:
        user.locked_until = datetime.now(UTC) + timedelta(seconds=LOCKOUT_DURATION_2)
    elif count >= LOCKOUT_THRESHOLD_1:
        user.locked_until = datetime.now(UTC) + timedelta(seconds=LOCKOUT_DURATION_1)

    await session.commit()


async def _record_success(user: User, session: AsyncSession) -> None:
    """Clear lockout state and refresh session activity on successful login."""
    from datetime import UTC, datetime

    user.last_activity = datetime.now(UTC)
    if user.login_fail_count or user.locked_until:
        user.login_fail_count = 0
        user.locked_until = None
    await session.commit()


def _create_auth_token_pair(user: User) -> tuple[str, str]:
    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    refresh_token = create_refresh_token(data={"sub": user.username})
    return access_token, refresh_token


def _should_use_secure_auth_cookies(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto")
    if forwarded_proto:
        return forwarded_proto.split(",", 1)[0].strip().lower() == "https"
    return request.scope.get("scheme") == "https"


def _set_auth_cookies(
    request: Request,
    response: Response,
    access_token: str,
    refresh_token: str,
) -> None:
    secure = _should_use_secure_auth_cookies(request)
    response.set_cookie(
        key=ACCESS_COOKIE_KEY,
        value=access_token,
        httponly=True,
        secure=secure,
        samesite=AUTH_COOKIE_SAMESITE,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path=ACCESS_COOKIE_PATH,
    )
    response.set_cookie(
        key=REFRESH_COOKIE_KEY,
        value=refresh_token,
        httponly=True,
        secure=secure,
        samesite=AUTH_COOKIE_SAMESITE,
        max_age=REFRESH_TOKEN_MAX_AGE,
        path=REFRESH_COOKIE_PATH,
    )


def _clear_auth_cookies(request: Request, response: Response) -> None:
    secure = _should_use_secure_auth_cookies(request)
    response.delete_cookie(
        key=ACCESS_COOKIE_KEY,
        path=ACCESS_COOKIE_PATH,
        httponly=True,
        secure=secure,
        samesite=AUTH_COOKIE_SAMESITE,
    )
    response.delete_cookie(
        key=REFRESH_COOKIE_KEY,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=secure,
        samesite=AUTH_COOKIE_SAMESITE,
    )
    response.delete_cookie("csrf_token", path="/")


def _token_response_payload(
    access_token: str,
    refresh_token: str | None,
) -> dict[str, str | None]:
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


def _mfa_pending_response(mfa_token: str) -> dict[str, str | None | bool]:
    return {
        **_token_response_payload(mfa_token, None),
        "mfa_required": True,
    }


def _extract_bearer_token(
    request: Request,
    *,
    cookie_key: str | None = None,
) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    if cookie_key:
        return request.cookies.get(cookie_key)
    return None


def _extract_refresh_token(
    request: Request,
    body_refresh_token: str | None,
) -> str | None:
    return request.cookies.get(REFRESH_COOKIE_KEY) or body_refresh_token


async def _get_user_by_username(
    session: AsyncSession,
    username: str,
) -> User | None:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def _decode_token_or_http_error(token: str, detail: str) -> dict[str, object]:
    try:
        return await decode_token(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
        )


async def _validate_refresh_token_payload(
    refresh_token: str,
) -> tuple[dict[str, object], str]:
    try:
        payload = await decode_token(refresh_token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    username = payload.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject",
        )

    return payload, username


def _raise_if_token_invalidated(user: User, payload: dict[str, object]) -> None:
    if not user.invalidated_before:
        return

    token_iat = payload.get("iat")
    if token_iat and datetime.fromtimestamp(token_iat, tz=UTC) < user.invalidated_before:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalidated",
        )
