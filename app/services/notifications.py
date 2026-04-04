"""
Notification service for mission events.

Sends notifications via webhook (ntfy.sh, Slack, Discord, etc.)
when key mission events occur.
"""

import ipaddress
import logging
import socket
import urllib.parse

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def _is_safe_url(url: str) -> bool:
    """Validate webhook URL is not targeting internal/private networks."""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        for info in socket.getaddrinfo(hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        return True
    except (socket.gaierror, ValueError, OSError):
        return False


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

    if not _is_safe_url(url):
        logger.warning("Blocked notification to unsafe webhook URL: %s", url)
        return False

    try:
        headers = {"Title": title, "Priority": priority}
        if tags:
            headers["Tags"] = ",".join(tags)

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, content=message, headers=headers)
            return response.status_code < 400
    except (OSError, RuntimeError, ConnectionError, TimeoutError) as e:
        logger.debug("Notification failed: %s", e)
        return False


async def notify_mission_started(target: str, directive: str) -> None:
    """Notify when a mission starts."""
    await send_notification(
        title="Mission Started",
        message=f"Target: {target}\nDirective: {directive[:100]}",
        tags=["rocket"],
    )


async def notify_mission_completed(target: str, findings_count: int, critical_count: int) -> None:
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
