"""
Notification service for mission events.

Sends notifications via webhook (ntfy.sh, Slack, Discord, etc.)
when key mission events occur.  Also provides an in-app notification
store backed by the cache_entries table.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import socket
import urllib.parse
import uuid
from datetime import UTC, datetime
from enum import StrEnum

import httpx
from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger("spectra.notifications")


# ---------------------------------------------------------------------------
# Safe-URL validation (SSRF protection)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Webhook helpers (existing functionality)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# In-app notification models & service
# ---------------------------------------------------------------------------


class NotificationChannel(StrEnum):
    IN_APP = "in_app"
    WEBHOOK = "webhook"
    EMAIL = "email"


class NotificationPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Notification(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    user_id: str
    title: str
    message: str
    channel: NotificationChannel = NotificationChannel.IN_APP
    priority: NotificationPriority = NotificationPriority.MEDIUM
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    read: bool = False
    event_type: str | None = None
    metadata: dict = Field(default_factory=dict)


_NOTIFICATION_NS = "notifications"
_TTL_HOURS = 24 * 30  # 30 days


class NotificationService:
    """Handles in-app user notifications backed by the cache table."""

    # --- write ---------------------------------------------------------

    async def send(self, notification: Notification) -> bool:
        """Persist an in-app notification."""
        logger.info(
            "Notification [%s] to %s: %s",
            notification.priority,
            notification.user_id,
            notification.title,
        )
        if notification.channel == NotificationChannel.WEBHOOK:
            return await self._deliver_webhook(notification)
        return await self._store_in_app(notification)

    async def _store_in_app(self, notification: Notification) -> bool:
        from app.services.cache import CacheService

        key = f"{notification.user_id}:{notification.id}"
        await CacheService.set(
            _NOTIFICATION_NS,
            key,
            notification.model_dump_json(),
            ttl_hours=_TTL_HOURS,
        )
        return True

    async def _deliver_webhook(self, notification: Notification) -> bool:
        return await send_notification(
            title=notification.title,
            message=notification.message,
            priority=notification.priority.value,
        )

    # --- read / update -------------------------------------------------

    async def get_user_notifications(
        self,
        user_id: str,
        *,
        limit: int = 50,
    ) -> list[dict]:
        """Return recent notifications for *user_id* (newest first)."""
        from app.services.cache import CacheService

        rows = await CacheService.scan_prefix(_NOTIFICATION_NS, f"{user_id}:")
        items = []
        for raw in rows:
            try:
                items.append(json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                continue
        items.sort(key=lambda n: n.get("created_at", ""), reverse=True)
        return items[:limit]

    async def get_unread_count(self, user_id: str) -> int:
        notes = await self.get_user_notifications(user_id)
        return sum(1 for n in notes if not n.get("read"))

    async def mark_read(self, user_id: str, notification_id: str) -> bool:
        from app.services.cache import CacheService

        key = f"{user_id}:{notification_id}"
        raw = await CacheService.get(_NOTIFICATION_NS, key)
        if raw is None:
            return False
        data = json.loads(raw)
        data["read"] = True
        await CacheService.set(_NOTIFICATION_NS, key, json.dumps(data), ttl_hours=_TTL_HOURS)
        return True

    async def delete(self, user_id: str, notification_id: str) -> bool:
        from app.services.cache import CacheService

        key = f"{user_id}:{notification_id}"
        raw = await CacheService.get(_NOTIFICATION_NS, key)
        if raw is None:
            return False
        await CacheService.delete(_NOTIFICATION_NS, key)
        return True


# Singleton
notification_service = NotificationService()
