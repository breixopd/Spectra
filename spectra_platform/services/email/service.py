"""Email service — resolves the configured provider and sends emails."""

from __future__ import annotations

import logging

from spectra_platform.core.config import settings
from spectra_platform.services.email.providers import AbstractEmailProvider
from spectra_platform.services.email.templates import TEMPLATES, wrap_email

logger = logging.getLogger(__name__)


def _get_provider() -> AbstractEmailProvider:
    """Return the email provider based on config."""
    if settings.SMTP_HOST:
        from spectra_platform.services.email.providers.smtp import SMTPProvider

        return SMTPProvider()
    from spectra_platform.services.email.providers.console import ConsoleProvider

    return ConsoleProvider()


class EmailService:
    """High-level API for sending platform emails."""

    def __init__(self, provider: AbstractEmailProvider | None = None) -> None:
        self._provider = provider or _get_provider()

    async def send_email(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str | None = None,
    ) -> bool:
        """Send a raw email."""
        return await self._provider.send(to, subject, html_body, text_body)

    async def send_template(
        self,
        to: str,
        template_name: str,
        subject: str,
        **kwargs: str,
    ) -> bool:
        """Render a named template and send it."""
        template = TEMPLATES.get(template_name)
        if template is None:
            logger.error("Unknown email template: %s", template_name)
            return False
        content = template.format(**kwargs)
        html = wrap_email(content)
        return await self._provider.send(to, subject, html)
