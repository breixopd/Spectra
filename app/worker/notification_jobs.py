"""Background notification delivery — webhook, email."""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.services.mission.output_model import get_mission_finding_counts

logger = logging.getLogger(__name__)


async def send_webhook_notification(payload: dict, webhook_url: str) -> bool:
    """Deliver a webhook notification (POST JSON)."""
    from app.services.notifications import _is_safe_url

    if not _is_safe_url(webhook_url):
        logger.warning("Blocked webhook to unsafe URL: %s", webhook_url)
        return False

    import httpx

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(webhook_url, json=payload)
            success = resp.status_code < 400
            if not success:
                logger.warning("Webhook %s returned %d", webhook_url, resp.status_code)
            return success
    except (OSError, RuntimeError, ConnectionError, TimeoutError) as e:
        logger.error("Webhook delivery failed: %s", e)
        return False


async def send_mission_completion_notification(mission_id: str, session) -> None:
    """Notify relevant users that a mission has completed."""
    from app.models.mission import Mission
    from app.services.notifications import notify_mission_completed

    result = await session.execute(select(Mission).where(Mission.id == mission_id))
    mission = result.scalar_one_or_none()
    if not mission:
        logger.warning("Mission %s not found for notification", mission_id)
        return

    finding_counts = get_mission_finding_counts(mission)
    total = finding_counts["total"]
    critical = finding_counts["critical"]

    target = getattr(mission, "target", "unknown")
    await notify_mission_completed(target, total, critical)
    logger.info("Sent mission completion notification for %s", mission_id)


async def send_critical_finding_alert(finding_id: str, session) -> None:
    """Alert on critical/high severity findings."""
    from app.models.finding import Finding
    from app.services.notifications import send_notification

    result = await session.execute(select(Finding).where(Finding.id == finding_id))
    finding = result.scalar_one_or_none()
    if not finding:
        logger.warning("Finding %s not found for alert", finding_id)
        return

    severity = getattr(finding, "severity", "unknown")
    if severity.lower() not in ("critical", "high"):
        return

    title = getattr(finding, "title", "Security Finding")
    await send_notification(
        title=f"{severity.upper()} Finding: {title}",
        message=getattr(finding, "description", "")[:500],
        priority="urgent" if severity.lower() == "critical" else "high",
        tags=["warning"],
    )
    logger.info("Sent critical finding alert for %s", finding_id)
