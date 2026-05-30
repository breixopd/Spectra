"""Console email provider for development — logs emails instead of sending."""

from __future__ import annotations

import logging

from spectra_system.email.providers import AbstractEmailProvider

logger = logging.getLogger(__name__)


class ConsoleProvider(AbstractEmailProvider):
    """Prints emails to the log instead of sending them."""

    async def send(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str | None = None,
    ) -> bool:
        logger.info(
            "EMAIL → to=%s subject=%s\n---\n%s\n---",
            to,
            subject,
            text_body or html_body[:500],
        )
        return True
