"""Notification API Router."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.dependencies import get_current_active_user
from app.api.error_responses import not_found
from app.models.user import User
from app.services.notifications import notification_service

logger = logging.getLogger("spectra.api.notifications")

router = APIRouter(prefix="/notifications", tags=["Notifications"])


class NotificationOut(BaseModel):
    id: str
    user_id: str
    title: str
    message: str
    priority: str
    created_at: str
    read: bool
    event_type: str | None = None
    metadata: dict = {}


class UnreadCountOut(BaseModel):
    count: int


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    limit: int = 50,
    current_user: User = Depends(get_current_active_user),
):
    """Get the current user's notifications (newest first)."""
    return await notification_service.get_user_notifications(
        str(current_user.id),
        limit=limit,
    )


@router.get("/unread-count", response_model=UnreadCountOut)
async def unread_count(
    current_user: User = Depends(get_current_active_user),
):
    """Get the number of unread notifications."""
    count = await notification_service.get_unread_count(str(current_user.id))
    return UnreadCountOut(count=count)


@router.put("/{notification_id}/read")
async def mark_read(
    notification_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Mark a notification as read."""
    ok = await notification_service.mark_read(str(current_user.id), notification_id)
    if not ok:
        raise not_found("notification", notification_id)
    return {"status": "ok"}


@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Delete a notification."""
    ok = await notification_service.delete(str(current_user.id), notification_id)
    if not ok:
        raise not_found("notification", notification_id)
    return {"status": "ok"}
