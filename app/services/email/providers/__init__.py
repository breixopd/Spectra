"""Abstract base class for email providers."""

from __future__ import annotations

from abc import ABC, abstractmethod


class AbstractEmailProvider(ABC):
    """Interface for email delivery backends."""

    @abstractmethod
    async def send(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str | None = None,
    ) -> bool:
        """Send an email. Returns True on success."""
        ...
