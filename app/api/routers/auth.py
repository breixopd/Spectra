"""
Authentication Router.

Handles user login, setup, and token generation.
"""

import asyncio
import json
import logging
import threading
import time
from datetime import timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_active_user
from app.api.schemas import SystemSetupRequest, Token, UserResponse
from app.api.schemas.auth import ForgotPasswordRequest, ResetPasswordRequest
from app.core.config import settings
from app.core.database import get_async_session
from app.core.events import EventType, events
from app.core.rate_limit import RateLimits, limiter
from app.core.security import (
    JWTError,
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    invalidate_token,
    verify_password,
    verify_password_reset_token,
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


async def _persist_lockout_async() -> None:
    """Save lockout state to file asynchronously."""
    await asyncio.to_thread(_persist_lockout)


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


@router.post(
    "/token",
    response_model=Token,
    summary="Login",
    description="OAuth2-compatible token endpoint. Returns JWT access and refresh tokens.",
)
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

    # Set HttpOnly cookie for browser-based auth
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )

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


@router.get(
    "/setup/status",
    response_model=dict,
    summary="Check setup status",
    description="Returns whether the initial admin setup has been completed.",
)
async def check_setup_status(
    session: AsyncSession = Depends(get_async_session),
):
    """Check if the system is already set up."""
    stmt = select(User.id).limit(1)
    result = await session.execute(stmt)
    is_setup = result.scalar_one_or_none() is not None
    return {"is_setup": is_setup}


@router.post(
    "/logout",
    response_model=dict,
    summary="Logout",
    description="Invalidate the current access token and clear the auth cookie.",
)
async def logout(request: Request, response: Response):
    """Logout by blacklisting the current access token and clearing cookie."""
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
    response.delete_cookie(key="access_token", path="/", httponly=True, secure=True, samesite="strict")
    return {"detail": "Successfully logged out"}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


@router.get("/me", response_model=dict, tags=["Auth"])
async def get_current_profile(
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Get current user's profile including plan info."""
    plan = None
    if user.plan_id:
        from app.models.plan import Plan

        result = await session.execute(select(Plan).where(Plan.id == user.plan_id))
        plan = result.scalar_one_or_none()

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_superuser": user.is_superuser,
        "plan": {
            "id": plan.id,
            "name": plan.name,
            "display_name": plan.display_name,
            "features": plan.features,
            "max_concurrent_missions": plan.max_concurrent_missions,
            "max_targets": plan.max_targets,
        } if plan else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.get("/me/usage", response_model=dict, tags=["Auth"])
async def get_usage_summary(
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Get current user's usage stats vs plan limits."""
    from app.services.billing.quota_enforcement import QuotaService

    return await QuotaService.get_usage_summary(str(user.id), session)


@router.post("/change-password", response_model=dict, tags=["Auth"])
@limiter.limit("5/minute")
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Change current user's password."""
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(400, "Current password is incorrect")

    user.hashed_password = get_password_hash(body.new_password)
    await session.commit()
    return {"detail": "Password changed successfully"}


@router.post("/forgot-password", status_code=204)
@limiter.limit("3/minute")
async def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Request a password reset email. Always returns 204 to avoid user enumeration."""
    from app.repositories.user import UserRepository

    user_repo = UserRepository(session)
    user = await user_repo.get_by_email(body.email)
    if user:
        reset_token = create_password_reset_token(str(user.id))
        # In production, send reset_token via email. For now, log it.
        logger.info("Password reset requested for user %s (token generated)", user.id)
        _ = reset_token  # Will be used when email service is integrated
    return Response(status_code=204)


@router.post("/reset-password", response_model=dict)
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    body: ResetPasswordRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Reset password using a valid reset token."""
    user_id = verify_password_reset_token(body.token)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    from app.repositories.user import UserRepository

    user_repo = UserRepository(session)
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user.hashed_password = get_password_hash(body.new_password)
    await session.commit()
    return {"message": "Password reset successfully"}


# ---------------------------------------------------------------------------
# API Key Management
# ---------------------------------------------------------------------------


class CreateApiKeyRequest(BaseModel):
    name: str = Field(default="default", max_length=100, min_length=1)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


@router.post("/api-keys", response_model=dict, tags=["API Keys"])
async def create_api_key(
    body: CreateApiKeyRequest = Body(CreateApiKeyRequest()),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Create a new API key for the current user. Returns the raw key once."""
    import hashlib
    import secrets
    from datetime import UTC, datetime, timedelta

    from app.repositories.api_key import ApiKeyRepository

    repo = ApiKeyRepository(session)

    # Enforce max 10 active keys per user
    existing = await repo.get_active_by_user(str(current_user.id))
    if len(existing) >= 10:
        raise HTTPException(
            status_code=400,
            detail="Maximum of 10 active API keys allowed",
        )

    raw_key = f"sk-{secrets.token_urlsafe(40)}"
    prefix = raw_key[:8]
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    expires_at = None
    if body.expires_in_days:
        expires_at = datetime.now(UTC) + timedelta(days=body.expires_in_days)

    api_key = await repo.create(
        user_id=str(current_user.id),
        name=body.name,
        key_hash=key_hash,
        key_prefix=prefix,
        scopes=[],
        is_active=True,
        expires_at=expires_at,
    )
    await session.commit()

    return {
        "id": api_key.id,
        "name": api_key.name,
        "key": raw_key,
        "prefix": prefix,
        "created_at": api_key.created_at.isoformat(),
        "expires_at": api_key.expires_at.isoformat() if api_key.expires_at else None,
    }


@router.get("/api-keys", response_model=list[dict], tags=["API Keys"])
async def list_api_keys(
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """List the current user's API keys (masked)."""
    from app.repositories.api_key import ApiKeyRepository

    repo = ApiKeyRepository(session)
    keys = await repo.get_by_user_id(str(current_user.id))
    return [
        {
            "id": k.id,
            "name": k.name,
            "key_prefix": k.key_prefix,
            "is_active": k.is_active,
            "created_at": k.created_at.isoformat(),
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "expires_at": k.expires_at.isoformat() if k.expires_at else None,
        }
        for k in keys
    ]


@router.delete("/api-keys/{key_id}", response_model=dict, tags=["API Keys"])
async def revoke_api_key(
    key_id: str,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Revoke an API key owned by the current user."""
    from app.repositories.api_key import ApiKeyRepository

    repo = ApiKeyRepository(session)
    api_key = await repo.get_by_id(key_id)

    if api_key is None or api_key.user_id != str(current_user.id):
        raise HTTPException(status_code=404, detail="API key not found")

    await repo.deactivate(key_id)
    await session.commit()
    return {"message": "API key revoked"}
