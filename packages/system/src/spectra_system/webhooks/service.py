"""Webhook service — register, list, and fire webhooks."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_common.constants import WEBHOOK_MAX_RETRIES
from spectra_common.utils.url_validation import is_safe_url
from spectra_system.webhooks.models import Webhook

logger = logging.getLogger(__name__)

SUPPORTED_EVENTS = frozenset(
    {
        "mission.started",
        "mission.completed",
        "finding.new",
        "scan.error",
    }
)

MAX_RETRIES = WEBHOOK_MAX_RETRIES
RETRY_DELAYS = [1, 5, 15]  # seconds


class WebhookService:
    """Register webhooks and fire events with async delivery + retry."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register(
        self,
        user_id: str,
        url: str,
        events: list[str],
        secret: str | None = None,
        description: str | None = None,
    ) -> Webhook:
        """Register a new webhook endpoint."""
        if not await is_safe_url(url):
            raise ValueError("Webhook URL points to a private/internal address")
        invalid = set(events) - SUPPORTED_EVENTS
        if invalid:
            raise ValueError(f"Unsupported webhook events: {invalid}")
        wh = Webhook(
            user_id=user_id,
            url=url,
            events=events,
            secret=secret,
            description=description,
        )
        self._session.add(wh)
        await self._session.commit()
        await self._session.refresh(wh)
        return wh

    async def list_for_user(self, user_id: str) -> list[Webhook]:
        """List all webhooks for a user."""
        result = await self._session.execute(
            select(Webhook).where(Webhook.user_id == user_id, Webhook.is_active.is_(True))
        )
        return list(result.scalars().all())

    async def delete(self, webhook_id: str, user_id: str) -> bool:
        """Soft-delete a webhook by deactivating it."""
        result = await self._session.execute(
            select(Webhook).where(Webhook.id == webhook_id, Webhook.user_id == user_id)
        )
        wh = result.scalar_one_or_none()
        if not wh:
            return False
        wh.is_active = False
        await self._session.commit()
        return True

    async def fire(self, event: str, payload: dict[str, Any]) -> None:
        """Deliver an event to all matching active webhooks (fire-and-forget)."""
        result = await self._session.execute(select(Webhook).where(Webhook.is_active.is_(True)))
        hooks = result.scalars().all()
        for wh in hooks:
            if event in (wh.events or []):
                from spectra_common.tasks import create_safe_task

                create_safe_task(_deliver(wh, event, payload), name=f"webhook-{wh.id}")


async def _deliver(wh: Webhook, event: str, payload: dict[str, Any]) -> None:
    """Deliver a webhook with retries.

    Includes ``X-Spectra-Timestamp`` in the payload and HMAC computation so
    receivers can reject replays older than 5 minutes.
    """
    body = {"event": event, "data": payload}
    timestamp = str(int(time.time()))
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "X-Spectra-Timestamp": timestamp,
    }
    if wh.secret:
        import json

        raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
        sig_payload = f"{timestamp}.".encode() + raw
        sig = hmac.new(wh.secret.encode(), sig_payload, hashlib.sha256).hexdigest()
        headers["X-Spectra-Signature"] = f"sha256={sig}"

    async with httpx.AsyncClient(timeout=10) as client:
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.post(wh.url, json=body, headers=headers)
                if resp.status_code < 400:
                    logger.info("Webhook %s delivered %s (status %d)", wh.id, event, resp.status_code)
                    return
                logger.warning(
                    "Webhook %s got %d for %s (attempt %d)",
                    wh.id,
                    resp.status_code,
                    event,
                    attempt + 1,
                )
            except (OSError, RuntimeError, ConnectionError, TimeoutError):
                logger.warning(
                    "Webhook %s delivery failed for %s (attempt %d)", wh.id, event, attempt + 1, exc_info=True
                )
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAYS[attempt])

    logger.error("Webhook %s delivery exhausted retries for %s", wh.id, event)
