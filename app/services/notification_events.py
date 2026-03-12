"""Wire notification service to the EventBus.

Automatically sends in-app notifications when key events fire.
Import this module at startup (e.g. in lifespan) to register the handlers.
"""

from __future__ import annotations

import logging

from app.core.events import Event, EventType, events
from app.services.notifications import (
    Notification,
    NotificationPriority,
    notification_service,
)

logger = logging.getLogger("spectra.notification_events")


async def _on_mission_completed(event: Event) -> None:
    user_id = event.data.get("user_id")
    if not user_id:
        return
    target = event.data.get("target", "unknown")
    findings = event.data.get("findings_count", 0)
    await notification_service.send(
        Notification(
            user_id=user_id,
            title="Mission Completed",
            message=f"Mission against {target} finished with {findings} findings.",
            priority=NotificationPriority.MEDIUM,
            event_type=EventType.MISSION_COMPLETED,
        )
    )


async def _on_mission_failed(event: Event) -> None:
    user_id = event.data.get("user_id")
    if not user_id:
        return
    target = event.data.get("target", "unknown")
    reason = event.data.get("reason", "")
    await notification_service.send(
        Notification(
            user_id=user_id,
            title="Mission Failed",
            message=f"Mission against {target} failed. {reason}".strip(),
            priority=NotificationPriority.HIGH,
            event_type=EventType.MISSION_FAILED,
        )
    )


async def _on_critical_finding(event: Event) -> None:
    severity = str(event.data.get("severity", "")).lower()
    if severity != "critical":
        return
    user_id = event.data.get("user_id")
    if not user_id:
        return
    title = event.data.get("title", "Critical finding")
    await notification_service.send(
        Notification(
            user_id=user_id,
            title="Critical Finding Discovered",
            message=title,
            priority=NotificationPriority.CRITICAL,
            event_type=EventType.FINDING_DISCOVERED,
        )
    )


def register_notification_handlers() -> None:
    """Subscribe notification handlers to the global event bus."""
    events.subscribe(EventType.MISSION_COMPLETED, _on_mission_completed)
    events.subscribe(EventType.MISSION_FAILED, _on_mission_failed)
    events.subscribe(EventType.FINDING_DISCOVERED, _on_critical_finding)
    logger.info("Notification event handlers registered")
