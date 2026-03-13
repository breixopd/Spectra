"""Admin email management endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from app.api.dependencies import get_current_active_user
from app.core.rbac import Permission, require_permission
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


class TestEmailRequest(BaseModel):
    to: EmailStr


class UpdateTemplateRequest(BaseModel):
    content: str


@router.post("/api/admin/email/test")
async def send_test_email(
    body: TestEmailRequest,
    current_user: User = Depends(get_current_active_user),
    _perm=require_permission(Permission.MANAGE_SETTINGS),
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
    current_user: User = Depends(get_current_active_user),
    _perm=require_permission(Permission.MANAGE_SETTINGS),
):
    """Return all email templates."""
    from app.services.email.templates import TEMPLATES

    return {name: tpl for name, tpl in TEMPLATES.items()}


@router.put("/api/admin/email/templates/{name}")
async def update_email_template(
    name: str,
    body: UpdateTemplateRequest,
    current_user: User = Depends(get_current_active_user),
    _perm=require_permission(Permission.MANAGE_SETTINGS),
):
    """Update an email template by name."""
    from app.services.email.templates import TEMPLATES

    if name not in TEMPLATES:
        raise HTTPException(status_code=404, detail=f"Template '{name}' not found")
    TEMPLATES[name] = body.content
    return {"status": "updated", "template": name}
