"""TOTP / MFA setup, verify, and disable endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rate_limit import RateLimits, limiter
from app.auth.security import (
    JWTError,
    decode_token,
    decrypt_mfa_secret,
    encrypt_mfa_secret,
    invalidate_token,
    verify_password,
    verify_totp,
)
from app.core.database import get_async_session
from app.models.audit_log import AuditEventType
from app.models.user import User
from app.services.system.audit import log_event as audit_log_event
from spectra_api.api.dependencies import get_current_active_user
from spectra_api.api.routers.auth._helpers import (
    _check_lockout,
    _consume_totp_code_async,
    _create_auth_token_pair,
    _decode_token_or_http_error,
    _extract_bearer_token,
    _get_user_by_username,
    _record_failure,
    _set_auth_cookies,
    _token_response_payload,
)
from spectra_api.api.schemas.auth import MFADisableRequest, MFASetupResponse, MFAVerifyRequest

logger = logging.getLogger(__name__)

router = APIRouter()


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
    if not await _consume_totp_code_async(str(user.id), body.code):
        raise HTTPException(status_code=400, detail="TOTP code has already been used")

    user.mfa_enabled = True
    await session.commit()

    await audit_log_event(
        session,
        AuditEventType.MFA_ENABLED,
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

    payload = await _decode_token_or_http_error(token, "Invalid or expired MFA token")

    if not payload.get("mfa_pending"):
        raise HTTPException(status_code=400, detail="Token is not an MFA pending token")

    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = await _get_user_by_username(session, username)

    if not user or not user.is_active or not user.mfa_enabled or not user.mfa_secret:
        raise HTTPException(status_code=401, detail="Invalid MFA state")

    await _check_lockout(user)

    secret = decrypt_mfa_secret(user.mfa_secret)
    if not verify_totp(secret, body.code):
        await _record_failure(user, session)
        await audit_log_event(
            session,
            AuditEventType.LOGIN_FAILED,
            user_id=str(user.id),
            details={"reason": "mfa_failed", "username": username},
            request=request,
        )
        raise HTTPException(status_code=401, detail="Invalid TOTP code")
    if not await _consume_totp_code_async(str(user.id), body.code):
        raise HTTPException(status_code=401, detail="TOTP code has already been used")

    # Invalidate the partial MFA token
    await invalidate_token(token)

    await audit_log_event(
        session,
        AuditEventType.TOKEN_REVOKED,
        user_id=str(user.id),
        details={"username": username, "reason": "mfa_verified"},
        request=request,
    )

    access_token, refresh_token = _create_auth_token_pair(user)
    _set_auth_cookies(request, response, access_token, refresh_token)

    return _token_response_payload(access_token, refresh_token)


@router.post("/mfa/cancel", status_code=204, tags=["MFA"])
@limiter.limit(RateLimits.LOGIN)
async def cancel_mfa(request: Request):
    """Cancel MFA login and invalidate the pending token."""
    token = _extract_bearer_token(request)
    if not token:
        return Response(status_code=204)
    try:
        payload = await decode_token(token)
    except (JWTError, Exception):
        return Response(status_code=204)

    if payload.get("mfa_pending"):
        await invalidate_token(token)

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
    if not await _consume_totp_code_async(str(user.id), body.code):
        raise HTTPException(status_code=400, detail="TOTP code has already been used")

    user.mfa_enabled = False
    user.mfa_secret = None
    await session.commit()

    await audit_log_event(
        session,
        AuditEventType.MFA_DISABLED,
        user_id=str(user.id),
        details={"username": user.username},
        request=request,
    )

    return {"detail": "MFA disabled successfully"}
