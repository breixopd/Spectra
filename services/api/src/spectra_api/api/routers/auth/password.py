"""Password change, forgot, and reset endpoints."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rate_limit import RateLimits, limiter
from app.auth.security import (
    create_password_reset_token,
    get_password_hash,
    invalidate_token,
    verify_password,
    verify_password_reset_token,
)
from app.core.config import settings
from app.core.database import get_async_session
from app.models.audit_log import AuditEventType
from app.models.user import User
from app.services.system.audit import log_event as audit_log_event
from spectra_api.api.dependencies import get_current_active_user
from spectra_api.api.routers.auth.schemas import ChangePasswordRequest
from spectra_api.api.schemas.auth import ForgotPasswordRequest, ResetPasswordRequest

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
    from app.repositories.user import UserRepository
    from app.services.email import EmailService

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

    await invalidate_token(body.token)

    await audit_log_event(
        session,
        AuditEventType.PASSWORD_RESET,
        user_id=str(user.id),
        details={"user_id": str(user.id)},
        request=request,
    )

    return {"message": "Password reset successfully"}
