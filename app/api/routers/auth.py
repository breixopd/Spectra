"""
Authentication Router.

Handles user login, setup, and token generation.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_active_user
from app.api.schemas import SystemSetupRequest, Token, UserResponse
from app.api.schemas.auth import (
    ForgotPasswordRequest,
    MFADisableRequest,
    MFASetupResponse,
    MFAVerifyRequest,
    ResetPasswordRequest,
)
from app.api.schemas.system import DeleteAccountRequest
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
    decrypt_mfa_secret,
    encrypt_mfa_secret,
    get_password_hash,
    invalidate_token,
    verify_password,
    verify_password_reset_token,
    verify_totp,
)
from app.core.telemetry import telemetry
from app.models.audit_log import AuditEventType
from app.models.user import User
from app.services.system.audit import log_event as audit_log_event

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Account Lockout (DB-backed) ---
LOCKOUT_THRESHOLD_1 = 5   # failures before first lockout
LOCKOUT_DURATION_1 = 300  # 5 minutes
LOCKOUT_THRESHOLD_2 = 10  # failures before extended lockout
LOCKOUT_DURATION_2 = 1800 # 30 minutes
ACCESS_COOKIE_KEY = "access_token"
REFRESH_COOKIE_KEY = "refresh_token"
ACCESS_COOKIE_PATH = "/"
REFRESH_COOKIE_PATH = "/api/v1/auth/refresh"
AUTH_COOKIE_SAMESITE = "strict"
REFRESH_TOKEN_MAX_AGE = 7 * 24 * 60 * 60
DUMMY_PASSWORD_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewKyNiLXCJzFhWMu"


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
    """Clear lockout state on successful login."""
    if user.login_fail_count or user.locked_until:
        user.login_fail_count = 0
        user.locked_until = None
        await session.commit()


def _create_auth_token_pair(user: User) -> tuple[str, str]:
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role, "is_superuser": user.is_superuser},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    refresh_token = create_refresh_token(data={"sub": user.username})
    return access_token, refresh_token


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    response.set_cookie(
        key=ACCESS_COOKIE_KEY,
        value=access_token,
        httponly=True,
        secure=True,
        samesite=AUTH_COOKIE_SAMESITE,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path=ACCESS_COOKIE_PATH,
    )
    response.set_cookie(
        key=REFRESH_COOKIE_KEY,
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite=AUTH_COOKIE_SAMESITE,
        max_age=REFRESH_TOKEN_MAX_AGE,
        path=REFRESH_COOKIE_PATH,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(
        key=ACCESS_COOKIE_KEY,
        path=ACCESS_COOKIE_PATH,
        httponly=True,
        secure=True,
        samesite=AUTH_COOKIE_SAMESITE,
    )
    response.delete_cookie(
        key=REFRESH_COOKIE_KEY,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=True,
        samesite=AUTH_COOKIE_SAMESITE,
    )


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


def _decode_token_or_http_error(token: str, detail: str) -> dict[str, object]:
    try:
        return decode_token(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
        )


def _validate_refresh_token_payload(
    refresh_token: str,
) -> tuple[dict[str, object], str]:
    try:
        payload = decode_token(refresh_token)
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
    user = await _get_user_by_username(session, form_data.username)

    # Check account lockout after user lookup (user-based, not IP-based)
    # If user doesn't exist, skip lockout to avoid user enumeration
    if user:
        await _check_lockout(user)

    # Always verify password even if user doesn't exist (timing-safe)
    password_valid = verify_password(
        form_data.password, user.hashed_password if user else DUMMY_PASSWORD_HASH
    )

    if not user or not password_valid:
        logger.warning(
            "Failed login attempt for user '%s' from %s", form_data.username, client_ip
        )

        if user:
            await _record_failure(user, session)

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

    # Block unverified users when email verification is active
    if (settings.smtp_configured or settings.EMAIL_VERIFICATION_ENABLED) and not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email address before logging in. Check your inbox for the verification link.",
        )

    # If MFA is enabled, return a partial MFA token instead of full access
    if user.mfa_enabled:
        mfa_token = create_access_token(
            data={"sub": user.username, "mfa_pending": True},
            expires_delta=timedelta(minutes=5),
        )
        await _record_success(user, session)
        return _mfa_pending_response(mfa_token)

    access_token, refresh_token = _create_auth_token_pair(user)

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

    await _record_success(user, session)

    _set_auth_cookies(response, access_token, refresh_token)

    return _token_response_payload(access_token, refresh_token)


@router.post("/refresh", response_model=Token)
@limiter.limit(RateLimits.TOKEN_REFRESH)
async def refresh_token(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_async_session),
    body_refresh_token: str | None = Body(default=None, embed=True, alias="refresh_token"),
):
    """
    Refresh access token using a valid refresh token.
    Accepts the refresh token from an HttpOnly cookie (browser) or request body (API clients).
    """
    provided_refresh_token = _extract_refresh_token(request, body_refresh_token)
    if not provided_refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token required",
        )
    payload, username = _validate_refresh_token_payload(provided_refresh_token)

    # Check if user exists and is active
    user = await _get_user_by_username(session, username)

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    _raise_if_token_invalidated(user, payload)

    access_token, new_refresh_token = _create_auth_token_pair(user)
    _set_auth_cookies(response, access_token, new_refresh_token)

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
    summary="Logout",
    description="Invalidate the current access token and clear the auth cookie.",
)
async def logout(request: Request, response: Response, session: AsyncSession = Depends(get_async_session)):
    """Logout by blacklisting the current access token and clearing cookie."""
    token = _extract_bearer_token(request, cookie_key=ACCESS_COOKIE_KEY)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    payload = _decode_token_or_http_error(token, "Invalid token")
    invalidate_token(token)

    # Invalidate all tokens issued before now (covers refresh tokens too)
    username = payload.get("sub")
    if username:
        user = await _get_user_by_username(session, username)
        if user:
            user.invalidated_before = datetime.now(UTC)
            await session.commit()

    _clear_auth_cookies(response)
    return {"detail": "Successfully logged out"}


# --- MFA Endpoints ---


@router.post("/mfa/setup", response_model=MFASetupResponse, tags=["MFA"])
async def mfa_setup(
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Generate a TOTP secret and return provisioning URI. Does not enable MFA yet."""
    import pyotp

    if user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is already enabled")

    secret = pyotp.random_base32()
    user.mfa_secret = encrypt_mfa_secret(secret)
    await session.commit()

    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=user.email, issuer_name="Spectra")

    return MFASetupResponse(secret=secret, provisioning_uri=provisioning_uri)


@router.post("/mfa/verify-setup", tags=["MFA"])
async def mfa_verify_setup(
    request: Request,
    body: MFAVerifyRequest,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Verify a TOTP code and enable MFA for the user."""
    if user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is already enabled")
    if not user.mfa_secret:
        raise HTTPException(status_code=400, detail="MFA setup not initiated. Call /mfa/setup first.")

    secret = decrypt_mfa_secret(user.mfa_secret)
    if not verify_totp(secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")

    user.mfa_enabled = True
    await session.commit()

    await audit_log_event(
        session, AuditEventType.MFA_ENABLED,
        user_id=str(user.id),
        details={"username": user.username},
        request=request,
    )

    return {"detail": "MFA enabled successfully"}


@router.post("/mfa/verify", tags=["MFA"])
@limiter.limit(RateLimits.LOGIN)
async def mfa_verify_login(
    request: Request,
    response: Response,
    body: MFAVerifyRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Complete MFA login by verifying TOTP code with the partial MFA token."""
    token = _extract_bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    payload = _decode_token_or_http_error(token, "Invalid or expired MFA token")

    if not payload.get("mfa_pending"):
        raise HTTPException(status_code=400, detail="Token is not an MFA pending token")

    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = await _get_user_by_username(session, username)

    if not user or not user.is_active or not user.mfa_enabled or not user.mfa_secret:
        raise HTTPException(status_code=401, detail="Invalid MFA state")

    secret = decrypt_mfa_secret(user.mfa_secret)
    if not verify_totp(secret, body.code):
        raise HTTPException(status_code=401, detail="Invalid TOTP code")

    # Invalidate the partial MFA token
    invalidate_token(token)

    access_token, refresh_token = _create_auth_token_pair(user)
    _set_auth_cookies(response, access_token, refresh_token)

    return _token_response_payload(access_token, refresh_token)


@router.post("/mfa/cancel", status_code=204, tags=["MFA"])
@limiter.limit(RateLimits.LOGIN)
async def cancel_mfa(request: Request):
    """Cancel MFA login and invalidate the pending token."""
    token = _extract_bearer_token(request)
    if not token:
        return Response(status_code=204)
    try:
        payload = decode_token(token)
    except (JWTError, Exception):
        return Response(status_code=204)

    if payload.get("mfa_pending"):
        invalidate_token(token)

    return Response(status_code=204)


@router.post("/mfa/disable", tags=["MFA"])
async def mfa_disable(
    request: Request,
    body: MFADisableRequest,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Disable MFA. Requires current password and a valid TOTP code."""
    if not user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is not enabled")

    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    secret = decrypt_mfa_secret(user.mfa_secret)
    if not verify_totp(secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")

    user.mfa_enabled = False
    user.mfa_secret = None
    await session.commit()

    await audit_log_event(
        session, AuditEventType.MFA_DISABLED,
        user_id=str(user.id),
        details={"username": user.username},
        request=request,
    )

    return {"detail": "MFA disabled successfully"}


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


@router.get("/me", tags=["Auth"])
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

    # Check if user has preferences configured
    from app.models.user_preferences import UserPreferences

    prefs_result = await session.execute(
        select(UserPreferences.id).where(UserPreferences.user_id == str(user.id))
    )
    has_preferences = prefs_result.scalar_one_or_none() is not None

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_superuser": user.is_superuser,
        "mfa_enabled": user.mfa_enabled,
        "has_preferences": has_preferences,
        "preferences_url": "/api/v1/user/settings",
        "plan": {
            "id": plan.id,
            "name": plan.name,
            "display_name": plan.display_name,
            "features": plan.features,
            "max_concurrent_missions": plan.max_concurrent_missions,
            "max_missions_per_month": plan.max_missions_per_month,
            "max_targets": plan.max_targets,
            "max_storage_mb": plan.max_storage_mb,
            "max_api_requests_per_hour": plan.max_api_requests_per_hour,
        } if plan else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


class UpdateProfileRequest(BaseModel):
    email: str | None = None


@router.put("/me", tags=["Auth"])
@limiter.limit(RateLimits.PROFILE_UPDATE)
async def update_profile(
    request: Request,
    body: UpdateProfileRequest,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Update current user's profile."""
    if body.email is not None:
        import re
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', body.email):
            raise HTTPException(status_code=400, detail="Invalid email format")
        existing = await session.execute(
            select(User).where(User.email == body.email, User.id != user.id)
        )
        if existing.scalar_one_or_none():
            # Don't reveal whether an email exists — return success silently
            logger.warning("Email change conflict for user=%s target=%s", user.id, body.email)
            return {"detail": "Profile updated"}
        old_email = user.email
        user.email = body.email
        await session.commit()

        try:
            await audit_log_event(
                session, AuditEventType.SETTINGS_CHANGED,
                user_id=str(user.id),
                details={"action": "email_changed", "old_email": old_email, "new_email": body.email},
                request=request,
            )
        except (OSError, RuntimeError) as exc:
            logger.warning("Failed to log audit event for email change: %s", exc)
    else:
        await session.commit()
    return {"detail": "Profile updated"}


@router.post("/change-password", tags=["Auth"])
@limiter.limit(RateLimits.PASSWORD_CHANGE)
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
    user.invalidated_before = datetime.now(UTC)
    await session.commit()

    await audit_log_event(
        session, AuditEventType.PASSWORD_CHANGED,
        user_id=str(user.id),
        details={"username": user.username},
        request=request,
    )

    return {"detail": "Password changed successfully"}


@router.delete("/account", tags=["Auth"])
@limiter.limit(RateLimits.ACCOUNT_DELETE)
async def delete_account(
    request: Request,
    body: DeleteAccountRequest,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Permanently delete user account and all associated data.

    Requires password confirmation. This action is irreversible.
    Audit logs are preserved with user_id set to NULL.
    """
    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(400, "Password is incorrect")

    if user.is_superuser:
        stmt = select(func.count()).select_from(User).where(
            User.is_superuser.is_(True), User.is_active.is_(True)
        )
        result = await session.execute(stmt)
        if result.scalar_one() <= 1:
            raise HTTPException(400, "Cannot delete the last superuser account")

    user_id = str(user.id)
    username = user.username

    await audit_log_event(
        session, AuditEventType.ACCOUNT_DELETED,
        user_id=user_id,
        details={"username": username},
        request=request,
    )

    # Nullify audit log references before cascade
    from sqlalchemy import text

    await session.execute(
        text("UPDATE audit_logs SET user_id = NULL WHERE user_id = :uid"),
        {"uid": user_id},
    )

    await session.delete(user)
    await session.commit()

    logger.info("Account deleted: user_id=%s username=%s", user_id, username)

    return {"detail": "Account and all associated data have been permanently deleted"}


@router.post("/forgot-password", status_code=204)
@limiter.limit(RateLimits.FORGOT_PASSWORD)
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


@router.post("/reset-password")
@limiter.limit(RateLimits.RESET_PASSWORD)
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
    user.invalidated_before = datetime.now(UTC)
    await session.commit()

    await audit_log_event(
        session, AuditEventType.PASSWORD_RESET,
        user_id=str(user.id),
        details={"user_id": str(user.id)},
        request=request,
    )

    return {"message": "Password reset successfully"}


# --- API Keys ---


@router.get("/api-keys", summary="List API keys")
async def list_api_keys(
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """List current user's active API keys."""
    from app.models.plan import ApiKey

    stmt = (
        select(ApiKey)
        .where(ApiKey.user_id == str(user.id), ApiKey.is_active == True)  # noqa: E712
        .order_by(ApiKey.created_at.desc())
    )
    result = await session.execute(stmt)
    keys = result.scalars().all()
    return [
        {
            "id": str(k.id),
            "name": k.name,
            "prefix": k.key_prefix,
            "scopes": k.scopes,
            "created_at": k.created_at.isoformat() if k.created_at else None,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "expires_at": k.expires_at.isoformat() if k.expires_at else None,
        }
        for k in keys
    ]


@router.post("/api-keys", summary="Create API key", status_code=201)
async def create_api_key(
    request: Request,
    body: dict = Body(...),
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Create a new API key for the current user."""
    import hashlib
    import secrets

    from app.models.plan import ApiKey

    name = body.get("name", "Unnamed Key")
    scopes = body.get("scopes", [])

    raw_key = f"sk_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:10]

    api_key = ApiKey(
        user_id=str(user.id),
        name=name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        scopes=scopes,
        is_active=True,
    )
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)

    await audit_log_event(
        session,
        AuditEventType.API_KEY_CREATED,
        user_id=str(user.id),
        details={"key_name": name},
        request=request,
    )

    return {"id": str(api_key.id), "name": name, "key": raw_key, "prefix": key_prefix}


@router.delete("/api-keys/{key_id}", summary="Revoke API key")
async def revoke_api_key(
    key_id: str,
    request: Request,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Revoke an API key belonging to the current user."""
    from app.models.plan import ApiKey

    stmt = select(ApiKey).where(
        ApiKey.id == key_id, ApiKey.user_id == str(user.id)
    )
    result = await session.execute(stmt)
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    api_key.is_active = False
    await session.commit()

    await audit_log_event(
        session,
        AuditEventType.API_KEY_REVOKED,
        user_id=str(user.id),
        details={"key_name": api_key.name},
        request=request,
    )

    return {"detail": "API key revoked"}


# --- Activity Log ---


@router.get("/activity", summary="Get recent activity")
async def get_user_activity(
    limit: int = 20,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Return recent audit log entries for the current user."""
    from app.models.audit_log import AuditLog

    stmt = (
        select(AuditLog)
        .where(AuditLog.user_id == str(user.id))
        .order_by(AuditLog.created_at.desc())
        .limit(min(limit, 100))
    )
    result = await session.execute(stmt)
    logs = result.scalars().all()
    return [
        {
            "id": str(entry.id),
            "event_type": entry.event_type,
            "details": entry.details,
            "ip_address": entry.ip_address,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
        }
        for entry in logs
    ]
