"""Admin email management endpoints."""
import csv
import io
import logging
from html import escape as html_escape

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_async_session
from app.core.rate_limit import limiter
from app.core.rbac import Permission, require_permission
from app.core.security import (
    create_unsubscribe_token,
    verify_unsubscribe_token,
)
from app.models.user import User
from app.models.user_preferences import UserPreferences

logger = logging.getLogger(__name__)

router = APIRouter()


class TestEmailRequest(BaseModel):
    to: EmailStr


class UpdateTemplateRequest(BaseModel):
    content: str


class AnnouncementRequest(BaseModel):
    title: str
    content: str
    test_only: bool = False


def _unsubscribe_url(user_id: str) -> str:
    """Build the one-click unsubscribe URL for a user."""
    token = create_unsubscribe_token(user_id)
    base = settings.PLATFORM_BASE_URL.rstrip("/")
    return f"{base}/api/email/unsubscribe/{token}"


@router.post("/api/admin/email/test")
@limiter.limit("30/minute")
async def send_test_email(
    request: Request,
    body: TestEmailRequest,
    _perm: User = require_permission(Permission.MANAGE_SETTINGS),
):
    """Send a test email to verify SMTP configuration."""
    from app.services.email import EmailService
    from app.services.email.templates import wrap_email

    svc = EmailService()
    html = wrap_email(
        "<h1 style='color:#fff;font-size:22px;margin:0 0 16px;'>Test Email</h1>"
        "<p>If you received this, email sending is configured correctly.</p>"
    )
    ok = await svc.send_email(
        to=body.to,
        subject="Spectra \u2014 Test Email",
        html_body=html,
    )
    if ok:
        return {"status": "sent", "to": body.to}
    raise HTTPException(status_code=500, detail="Failed to send test email. Check SMTP settings.")


@router.get("/api/admin/email/templates")
async def get_email_templates(
    _perm: User = require_permission(Permission.MANAGE_SETTINGS),
):
    """Return all email templates."""
    from app.services.email.templates import TEMPLATES

    return dict(TEMPLATES.items())


@router.put("/api/admin/email/templates/{name}")
@limiter.limit("30/minute")
async def update_email_template(
    request: Request,
    name: str,
    body: UpdateTemplateRequest,
    _perm: User = require_permission(Permission.MANAGE_SETTINGS),
):
    """Update an email template by name."""
    from app.services.email.templates import TEMPLATES

    if name not in TEMPLATES:
        raise HTTPException(status_code=404, detail=f"Template '{name}' not found")
    TEMPLATES[name] = body.content
    return {"status": "updated", "template": name}


@router.post("/api/admin/email/announcement")
@limiter.limit("10/minute")
async def send_announcement(
    request: Request,
    body: AnnouncementRequest,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = require_permission(Permission.MANAGE_SETTINGS),
):
    """Send an announcement email to all opted-in users.

    If test_only=True, sends only to the admin's own email.
    """
    from app.services.email import EmailService
    from app.services.email.templates import TEMPLATES, wrap_email

    svc = EmailService()
    template = TEMPLATES["announcement"]
    sent = 0

    if body.test_only:
        unsub_url = _unsubscribe_url(str(current_user.id))
        content = template.format(title=html_escape(body.title), content=body.content)
        html = wrap_email(content, unsubscribe_url=unsub_url)
        ok = await svc.send_email(
            to=current_user.email,
            subject=f"Spectra \u2014 {body.title}",
            html_body=html,
        )
        if ok:
            sent = 1
    else:
        # Query opted-in users with a join to preferences
        stmt = (
            select(User.id, User.email)
            .join(UserPreferences, UserPreferences.user_id == User.id)
            .where(
                User.is_active.is_(True),
                UserPreferences.email_notifications.is_(True),
                UserPreferences.announcements_opt_in.is_(True),
            )
        )
        result = await session.execute(stmt)
        recipients = result.all()

        for user_id, email in recipients:
            unsub_url = _unsubscribe_url(str(user_id))
            content = template.format(title=html_escape(body.title), content=body.content)
            html = wrap_email(content, unsubscribe_url=unsub_url)
            ok = await svc.send_email(
                to=email,
                subject=f"Spectra \u2014 {body.title}",
                html_body=html,
            )
            if ok:
                sent += 1

    return {"status": "sent", "count": sent}


@router.get("/api/admin/email/export")
async def export_email_list(
    format: str = Query("csv", pattern="^(csv|json)$"),
    session: AsyncSession = Depends(get_async_session),
    _perm: User = require_permission(Permission.MANAGE_SETTINGS),
):
    """Export opted-in user emails for external mailing list."""
    stmt = (
        select(User.email, User.username)
        .join(UserPreferences, UserPreferences.user_id == User.id)
        .where(
            User.is_active.is_(True),
            UserPreferences.email_notifications.is_(True),
            UserPreferences.announcements_opt_in.is_(True),
        )
    )
    result = await session.execute(stmt)
    rows = result.all()

    if format == "json":
        return [{"email": email, "username": username} for email, username in rows]

    # CSV format
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["email", "username"])
    for email, username in rows:
        writer.writerow([email, username])
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=email_list.csv"},
    )


# --- Public unsubscribe endpoint (no auth required) ---

@router.get("/api/email/unsubscribe/{token}", response_class=HTMLResponse)
async def unsubscribe(
    token: str,
    session: AsyncSession = Depends(get_async_session),
):
    """One-click unsubscribe from announcements."""
    user_id = verify_unsubscribe_token(token)
    if not user_id:
        return HTMLResponse(
            "<h1>Invalid or expired unsubscribe link.</h1>",
            status_code=400,
        )

    stmt = select(UserPreferences).where(UserPreferences.user_id == user_id)
    result = await session.execute(stmt)
    prefs = result.scalar_one_or_none()

    if prefs is None:
        return HTMLResponse(
            "<h1>User preferences not found.</h1>",
            status_code=404,
        )

    prefs.announcements_opt_in = False
    await session.commit()
    return HTMLResponse("<h1>You have been unsubscribed from announcements.</h1>")
