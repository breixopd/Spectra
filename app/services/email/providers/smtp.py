"""SMTP email provider using aiosmtplib."""

from __future__ import annotations

import logging
from email.message import EmailMessage

from app.core.config import settings
from app.services.email.providers import AbstractEmailProvider

logger = logging.getLogger("spectra.email.smtp")


class SMTPProvider(AbstractEmailProvider):
    """Sends email via SMTP using aiosmtplib."""

    async def send(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str | None = None,
    ) -> bool:
        try:
            import aiosmtplib
        except ImportError:
            logger.error("aiosmtplib not installed — cannot send email via SMTP")
            return False

        msg = EmailMessage()
        msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
        msg["To"] = to
        msg["Subject"] = subject
        if text_body:
            msg.set_content(text_body)
        msg.add_alternative(html_body, subtype="html")

        try:
            await aiosmtplib.send(
                msg,
                hostname=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                username=settings.SMTP_USER or None,
                password=settings.SMTP_PASSWORD.get_secret_value() or None,
                use_tls=settings.SMTP_USE_TLS,
            )
            logger.info("Email sent to %s: %s", to, subject)
            return True
        except Exception:
            logger.exception("Failed to send email to %s", to)
            return False
