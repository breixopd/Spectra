"""Shared email verification helpers for registration and admin user creation."""

import logging

from fastapi import Request

from app.core.config import settings

logger = logging.getLogger(__name__)


def build_email_verification_url(request: Request | None, user_id: str) -> str | None:
    if request is None and not settings.PLATFORM_BASE_URL:
        return None

    from app.auth.security import create_email_verification_token

    token = create_email_verification_token(user_id)
    base_url = settings.PLATFORM_BASE_URL or str(request.base_url).rstrip("/")
    return f"{base_url}/verify-email?token={token}"


async def send_registration_verification_email(request: Request, username: str, email: str, user_id: str) -> bool:
    try:
        from app.services.email import EmailService

        verify_url = build_email_verification_url(request, user_id)
        if not verify_url:
            return False

        email_svc = EmailService()
        sent = await email_svc.send_template(
            to=email,
            template_name="email_verification",
            subject="Verify your Spectra account",
            username=username,
            verify_url=verify_url,
        )
        return bool(sent)
    except (OSError, RuntimeError, ConnectionError):
        logger.exception("Failed to send verification email to %s", username)
        return False
