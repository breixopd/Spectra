"""
Authentication Router.

Handles user login, setup, and token generation.
"""

import json
import logging
import threading
import time
from datetime import timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import SystemSetupRequest, Token, UserResponse
from app.core.config import settings
from app.core.database import get_async_session
from app.core.events import EventType, events
from app.core.rate_limit import RateLimits, limiter
from app.core.security import (
    JWTError,
    create_access_token,
    create_refresh_token,
    decode_token,
    invalidate_token,
    verify_password,
)
from app.core.telemetry import telemetry
from app.models.audit_log import AuditEventType
from app.models.user import User
from app.services.system.audit import log_event as audit_log_event

logger = logging.getLogger("spectra.api.auth")

router = APIRouter()


# --- Persistent Account Lockout ---
_LOCKOUT_FILE = Path("data/auth/.lockout_state.json")

_login_failures: dict[str, dict] = {}  # ip -> {"count": int, "locked_until": float}
_lockout_lock = threading.Lock()
_lockout_loaded = False

LOCKOUT_THRESHOLD_1 = 5   # failures before first lockout
LOCKOUT_DURATION_1 = 300  # 5 minutes in seconds
LOCKOUT_THRESHOLD_2 = 10  # failures before extended lockout
LOCKOUT_DURATION_2 = 1800 # 30 minutes in seconds


def _ensure_lockout_loaded() -> None:
    """Load lockout state from persistent storage once."""
    global _lockout_loaded
    if _lockout_loaded:
        return
    with _lockout_lock:
        if _lockout_loaded:
            return
        try:
            if _LOCKOUT_FILE.exists():
                data = json.loads(_LOCKOUT_FILE.read_text())
                now = time.time()
                for ip, entry in data.items():
                    locked_until = entry.get("locked_until", 0)
                    # Only load entries that are still locked or have recent failures
                    if locked_until > now or entry.get("count", 0) > 0:
                        _login_failures[ip] = entry
        except Exception as exc:
            logger.warning("Failed to load lockout state: %s", exc)
        _lockout_loaded = True


def _persist_lockout() -> None:
    """Save lockout state to file (call while holding lock)."""
    try:
        _LOCKOUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _LOCKOUT_FILE.write_text(json.dumps(_login_failures))
    except Exception as exc:
        logger.warning("Failed to persist lockout state: %s", exc)


def _check_lockout(ip: str) -> None:
    """Raise 429 if the IP is currently locked out."""
    _ensure_lockout_loaded()
    with _lockout_lock:
        entry = _login_failures.get(ip)
        if not entry:
            return
        locked_until = entry.get("locked_until", 0)
        if locked_until and time.time() < locked_until:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Account temporarily locked due to too many failed attempts",
            )
        # If lockout expired, keep count for escalation but clear lock
        if locked_until and time.time() >= locked_until:
            entry["locked_until"] = 0


def _record_failure(ip: str) -> None:
    """Record a failed login attempt and apply lockout if threshold reached."""
    _ensure_lockout_loaded()
    with _lockout_lock:
        entry = _login_failures.setdefault(ip, {"count": 0, "locked_until": 0})
        entry["count"] = entry.get("count", 0) + 1
        count = entry["count"]
        if count >= LOCKOUT_THRESHOLD_2:
            entry["locked_until"] = time.time() + LOCKOUT_DURATION_2
        elif count >= LOCKOUT_THRESHOLD_1:
            entry["locked_until"] = time.time() + LOCKOUT_DURATION_1
        _persist_lockout()


def _reset_failures(ip: str) -> None:
    """Reset failure count on successful login."""
    _ensure_lockout_loaded()
    with _lockout_lock:
        _login_failures.pop(ip, None)
        _persist_lockout()


@router.post("/token", response_model=Token)
@limiter.limit(RateLimits.LOGIN)
async def login_for_access_token(
    request: Request,
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: AsyncSession = Depends(get_async_session),
):
    """
    OAuth2 compatible token login, get an access token for future requests.

    Rate limited to 5 attempts per minute per IP address.
    """
    client_ip = request.client.host if request.client else "unknown"

    # Check account lockout before attempting auth
    _check_lockout(client_ip)

    # Find user
    stmt = select(User).where(User.username == form_data.username)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    # Always verify password even if user doesn't exist (timing-safe)
    dummy_hash = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewKyNiLXCJzFhWMu"
    password_valid = verify_password(
        form_data.password, user.hashed_password if user else dummy_hash
    )

    if not user or not password_valid:
        logger.warning(
            "Failed login attempt for user '%s' from %s", form_data.username, client_ip
        )

        _record_failure(client_ip)

        # Emit failed login event
        await events.emit(
            EventType.LOGIN_FAILED,
            source="auth",
            username=form_data.username,
            client_ip=client_ip,
        )
        telemetry.increment_counter(
            "login_failed", 1, {"reason": "invalid_credentials"}
        )

        # Audit log
        await audit_log_event(
            session,
            AuditEventType.LOGIN_FAILED,
            details={"username": form_data.username, "ip": client_ip},
            request=request,
        )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive"
        )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=access_token_expires,
    )

    refresh_token = create_refresh_token(
        data={"sub": user.username},
    )

    # Emit successful login event
    await events.emit(
        EventType.LOGIN_SUCCESS,
        source="auth",
        username=user.username,
        client_ip=client_ip,
    )
    telemetry.increment_counter("login_success", 1)

    # Audit log
    await audit_log_event(
        session,
        AuditEventType.LOGIN,
        user_id=str(user.id),
        details={"username": user.username, "ip": client_ip},
        request=request,
    )

    _reset_failures(client_ip)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post("/refresh", response_model=Token)
@limiter.limit("5/minute")
async def refresh_token(
    request: Request,
    response: Response,
    refresh_token: str = Body(..., embed=True),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Refresh access token using a valid refresh token.
    """
    try:
        payload = decode_token(refresh_token)
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
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    # Check if user exists and is active
    stmt = select(User).where(User.username == username)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # Create new access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=access_token_expires,
    )

    # Rotate refresh token
    new_refresh_token = create_refresh_token(
        data={"sub": user.username},
    )

    return Token(
        access_token=access_token,
        token_type="bearer",
        refresh_token=new_refresh_token,
    )


@router.post("/setup", response_model=UserResponse)
@limiter.limit(RateLimits.SETUP)
async def setup_admin_user(
    request: Request,  # Required by rate limiter
    response: Response,  # Required by rate limiter for headers
    setup_in: SystemSetupRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Create the initial admin user and configure system settings.
    Only allowed if no users exist in the database.
    """
    _ = request  # Used by rate limiter decorator
    # Check if any user exists
    stmt = select(User.id).limit(1)
    result = await session.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Setup already completed. Users exist.",
        )

    from app.services.system.setup import SystemSetupService

    setup_service = SystemSetupService(session)
    user = await setup_service.perform_setup(setup_in)

    return user


@router.get("/setup/status")
async def check_setup_status(
    session: AsyncSession = Depends(get_async_session),
):
    """Check if the system is already set up."""
    stmt = select(User.id).limit(1)
    result = await session.execute(stmt)
    is_setup = result.scalar_one_or_none() is not None
    return {"is_setup": is_setup}


@router.post("/logout")
async def logout(request: Request):
    """Logout by blacklisting the current access token."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    token = auth_header[7:]
    try:
        decode_token(token)  # Validate token is still valid
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    invalidate_token(token)
    return {"detail": "Successfully logged out"}
