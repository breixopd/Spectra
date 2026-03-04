"""
Notification service for mission events.

Sends notifications via webhook (ntfy.sh, Slack, Discord, etc.)
when key mission events occur.
"""

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger("spectra.notifications")


async def send_notification(
    title: str,
    message: str,
    priority: str = "default",
    tags: list[str] | None = None,
) -> bool:
    """Send a notification via the configured webhook."""
    url = getattr(settings, "NOTIFICATION_WEBHOOK", None)
    if not url:
        return False

    try:
        headers = {"Title": title, "Priority": priority}
        if tags:
            headers["Tags"] = ",".join(tags)

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, content=message, headers=headers)
            return response.status_code < 400
    except Exception as e:
        logger.debug("Notification failed: %s", e)
        return False


async def notify_mission_started(target: str, directive: str) -> None:
    """Notify when a mission starts."""
    await send_notification(
        title="Mission Started",
        message=f"Target: {target}\nDirective: {directive[:100]}",
        tags=["rocket"],
    )


async def notify_mission_completed(
    target: str, findings_count: int, critical_count: int
) -> None:
    """Notify when a mission completes."""
    await send_notification(
        title="Mission Complete",
        message=f"Target: {target}\nFindings: {findings_count} ({critical_count} critical)",
        priority="high" if critical_count > 0 else "default",
        tags=["white_check_mark"] if critical_count == 0 else ["warning"],
    )


async def notify_exploit_success(target: str, vector: str) -> None:
    """Notify when an exploit succeeds."""
    await send_notification(
        title="Exploit Successful!",
        message=f"Target: {target}\nVector: {vector}",
        priority="urgent",
        tags=["skull"],
    )


async def notify_mission_failed(target: str, error: str) -> None:
    """Notify when a mission fails."""
    await send_notification(
        title="Mission Failed",
        message=f"Target: {target}\nError: {error[:200]}",
        priority="high",
        tags=["x"],
    )
