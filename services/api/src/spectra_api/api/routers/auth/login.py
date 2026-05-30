"""Login, logout, and token refresh endpoints."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_api.api.routers.auth._helpers import (
    ACCESS_COOKIE_KEY,
    DUMMY_PASSWORD_HASH,
    _check_lockout,
    _clear_auth_cookies,
    _create_auth_token_pair,
    _decode_token_or_http_error,
    _extract_bearer_token,
    _extract_refresh_token,
    _get_user_by_username,
    _mfa_pending_response,
    _raise_if_token_invalidated,
    _record_failure,
    _record_success,
    _set_auth_cookies,
    _token_response_payload,
    _validate_refresh_token_payload,
)
from spectra_api.api.schemas.auth import Token
from spectra_auth.rate_limit import RateLimits, limiter
from spectra_auth.security import (
    create_access_token,
    invalidate_token,
    verify_password,
)
from spectra_common.config import settings
from spectra_infra.events import EventType, events
from spectra_observability.telemetry import telemetry
from spectra_persistence.database import get_async_session
from spectra_persistence.models.audit_log import AuditEventType
from spectra_system.audit import log_event as audit_log_event

logger = logging.getLogger(__name__)

router = APIRouter()


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

    Rate limited to 15 attempts per minute per IP address.
    """
    client_ip = request.client.host if request.client else "unknown"
    user = await _get_user_by_username(session, form_data.username)

    # Check account lockout after user lookup (user-based, not IP-based)
    # If user doesn't exist, skip lockout to avoid user enumeration
    if user:
        await _check_lockout(user)

    # Always verify password even if user doesn't exist (timing-safe)
    password_valid = verify_password(form_data.password, user.hashed_password if user else DUMMY_PASSWORD_HASH)

    if not user or not password_valid:
        logger.warning("Failed login attempt for user '%s' from %s", form_data.username, client_ip)

        if user:
            await _record_failure(user, session)

        # Emit failed login event
        await events.emit(
            EventType.LOGIN_FAILED,
            source="auth",
            username=form_data.username,
            client_ip=client_ip,
        )
        telemetry.increment_counter("login_failed", 1, {"reason": "invalid_credentials"})

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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")

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

    _set_auth_cookies(request, response, access_token, refresh_token)

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
    payload, username = await _validate_refresh_token_payload(provided_refresh_token)

    # Check if user exists and is active
    user = await _get_user_by_username(session, username)

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    _raise_if_token_invalidated(user, payload)
    await invalidate_token(provided_refresh_token)

    await audit_log_event(
        session,
        AuditEventType.TOKEN_REVOKED,
        user_id=str(user.id),
        details={"username": user.username, "reason": "token_refresh"},
        request=request,
    )

    access_token, new_refresh_token = _create_auth_token_pair(user)
    _set_auth_cookies(request, response, access_token, new_refresh_token)

    return Token(
        access_token=access_token,
        token_type="bearer",
        refresh_token=new_refresh_token,
    )


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
    payload = await _decode_token_or_http_error(token, "Invalid token")
    await invalidate_token(token)

    # Invalidate all tokens issued before now (covers refresh tokens too)
    username = payload.get("sub")
    if username:
        user = await _get_user_by_username(session, username)
        if user:
            user.invalidated_before = datetime.now(UTC)
            await session.commit()

            await audit_log_event(
                session,
                AuditEventType.LOGOUT,
                user_id=str(user.id),
                details={"username": user.username},
                request=request,
            )

    _clear_auth_cookies(request, response)
    return {"detail": "Successfully logged out"}
