"""Password change, forgot, and reset endpoints."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_api.api.dependencies import get_current_active_user
from spectra_api.api.routers.auth.schemas import ChangePasswordRequest
from spectra_api.api.schemas.auth import ForgotPasswordRequest, ResetPasswordRequest
from spectra_auth.rate_limit import RateLimits, limiter
from spectra_auth.security import (
    create_password_reset_token,
    get_password_hash,
    invalidate_token,
    is_token_blacklisted,
    verify_password,
    verify_password_reset_token,
)
from spectra_common.config import settings
from spectra_persistence.database import get_async_session
from spectra_persistence.models.audit_log import AuditEventType
from spectra_persistence.models.user import User
from spectra_system.audit import log_event as audit_log_event

logger = logging.getLogger(__name__)

router = APIRouter()


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
        session,
        AuditEventType.PASSWORD_CHANGED,
        user_id=str(user.id),
        details={"username": user.username},
        request=request,
    )

    return {"detail": "Password changed successfully"}


@router.post("/forgot-password", status_code=204)
@limiter.limit(RateLimits.FORGOT_PASSWORD)
async def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Request a password reset email. Always returns 204 to avoid user enumeration."""
    from spectra_persistence.repositories.user import UserRepository
    from spectra_system.email.service import EmailService

    user_repo = UserRepository(session)
    user = await user_repo.get_by_email(body.email)
    if user:
        reset_token = create_password_reset_token(str(user.id))
        base_url = settings.PLATFORM_BASE_URL or str(request.base_url).rstrip("/")
        reset_url = f"{base_url}/reset-password?token={reset_token}"
        try:
            sent = await EmailService().send_template(
                to=user.email,
                template_name="password_reset",
                subject=f"{settings.APP_NAME} - Password Reset",
                username=user.username,
                reset_url=reset_url,
            )
            if not sent:
                logger.warning("Password reset email provider returned false for user %s", user.id)
        except Exception:
            logger.exception("Failed to send password reset email for user %s", user.id)
    return Response(status_code=204)


@router.post("/reset-password")
@limiter.limit(RateLimits.RESET_PASSWORD)
async def reset_password(
    request: Request,
    response: Response,
    body: ResetPasswordRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Reset password using a valid reset token."""
    _ = response
    user_id = verify_password_reset_token(body.token)
    if user_id:
        # Password-reset tokens are one-time credentials.  The synchronous
        # signature check above cannot consult the durable revocation cache;
        # check it before changing the password so replay after a successful
        # reset is rejected across API replicas.
        try:
            if await is_token_blacklisted(body.token):
                logger.debug("Password reset rejected: token is revoked")
                user_id = None
        except Exception:
            logger.exception("Unable to verify password reset token revocation state")
            user_id = None
    if not user_id:
        logger.debug("Password reset rejected: token signature or type invalid")
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    from spectra_persistence.repositories.user import UserRepository

    user_repo = UserRepository(session)
    user = await user_repo.get_by_id(user_id)
    if not user:
        logger.debug("Password reset rejected: user %s not found", user_id)
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user.hashed_password = get_password_hash(body.new_password)
    user.invalidated_before = datetime.now(UTC)
    await session.commit()

    await invalidate_token(body.token)

    await audit_log_event(
        session,
        AuditEventType.PASSWORD_RESET,
        user_id=str(user.id),
        details={"user_id": str(user.id)},
        request=request,
    )

    return {"message": "Password reset successfully"}
