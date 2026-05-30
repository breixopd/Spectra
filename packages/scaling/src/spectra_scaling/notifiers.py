"""Pluggable notification targets for the autoscaler."""

from __future__ import annotations

import abc
import logging

logger = logging.getLogger(__name__)


class ScalingNotifier(abc.ABC):
    """Abstract notification target."""

    @abc.abstractmethod
    async def notify(self, title: str, message: str, level: str = "info") -> None: ...


class LogNotifier(ScalingNotifier):
    """Simple logging notifier (default, no dependencies)."""

    async def notify(self, title: str, message: str, level: str = "info") -> None:
        log_fn = getattr(
            logger, level if level in ("info", "warning", "error", "critical") else "info"
        )
        log_fn("[Autoscaler] %s — %s", title, message)


class SpectraNotifier(ScalingNotifier):
    """Spectra-specific notifier using the internal notification system."""

    async def notify(self, title: str, message: str, level: str = "info") -> None:
        try:
            from spectra_system.notifications import send_notification

            priority = "urgent" if level in ("error", "critical") else "normal"
            tags = ["autoscaler", level]
            await send_notification(title=title, message=message, priority=priority, tags=tags)
        except Exception:
            logger.warning("Failed to send Spectra notification: %s", title)
