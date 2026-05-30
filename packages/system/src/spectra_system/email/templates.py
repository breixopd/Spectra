"""Email template definitions for common platform emails."""

from __future__ import annotations

WELCOME = """
<h1 style="color:#fff;font-size:22px;margin:0 0 16px;">Welcome to Spectra</h1>
<p>Hi {username},</p>
<p>Your account has been created. You can log in at
<a href="{login_url}" style="color:#8b5cf6;">{login_url}</a>.</p>
"""

PASSWORD_RESET = """
<h1 style="color:#fff;font-size:22px;margin:0 0 16px;">Password Reset</h1>
<p>Hi {username},</p>
<p>Click the link below to reset your password. This link expires in 1 hour.</p>
<p><a href="{reset_url}" style="color:#8b5cf6;">{reset_url}</a></p>
<p>If you didn't request this, you can safely ignore this email.</p>
"""

MISSION_COMPLETE = """
<h1 style="color:#fff;font-size:22px;margin:0 0 16px;">Mission Complete</h1>
<p>Hi {username},</p>
<p>Your mission against <strong>{target}</strong> has finished.</p>
<ul>
  <li>Status: {status}</li>
  <li>Findings: {finding_count}</li>
</ul>
<p><a href="{report_url}" style="color:#8b5cf6;">View full report</a></p>
"""

ALERT = """
<h1 style="color:#fff;font-size:22px;margin:0 0 16px;">Security Alert</h1>
<p>Hi {username},</p>
<p><strong>{alert_title}</strong></p>
<p>{alert_message}</p>
"""

SUBSCRIPTION = """
<h1 style="color:#fff;font-size:22px;margin:0 0 16px;">Subscription Update</h1>
<p>Hi {username},</p>
<p>Your subscription has been updated:</p>
<ul>
  <li>Plan: <strong>{plan_name}</strong></li>
  <li>Status: {status}</li>
</ul>
<p><a href="{dashboard_url}" style="color:#8b5cf6;">Go to Dashboard</a></p>
"""

EMAIL_VERIFICATION = """
<h1 style="color:#fff;font-size:22px;margin:0 0 16px;">Verify Your Email</h1>
<p>Hi {username},</p>
<p>Please verify your email address by clicking the link below. This link expires in 24 hours.</p>
<p><a href="{verify_url}" style="color:#8b5cf6;">{verify_url}</a></p>
<p>If you didn't create this account, you can safely ignore this email.</p>
"""

TEMPLATES: dict[str, str] = {
    "welcome": WELCOME,
    "password_reset": PASSWORD_RESET,
    "mission_complete": MISSION_COMPLETE,
    "alert": ALERT,
    "subscription": SUBSCRIPTION,
    "email_verification": EMAIL_VERIFICATION,
    "announcement": """
<h1 style="color:#fff;font-size:22px;margin:0 0 16px;">{title}</h1>
<div style="padding: 20px 0; line-height: 1.6;">{content}</div>
""",
}


def wrap_email(content: str, unsubscribe_url: str | None = None) -> str:
    """Wrap template content in the branded Spectra email layout."""
    if unsubscribe_url:
        unsub_link = f'<a href="{unsubscribe_url}" style="color:#8b5cf6;">Unsubscribe</a>'
    else:
        unsub_link = '<a href="#" style="color:#8b5cf6;">Unsubscribe</a>'
    return (
        "<!DOCTYPE html>"
        '<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>'
        "<body style=\"margin:0;padding:0;background:#0a0a0f;font-family:'Segoe UI',system-ui,sans-serif;\">"
        '<table width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0f;padding:40px 20px;">'
        '<tr><td align="center">'
        '<table width="600" cellpadding="0" cellspacing="0" style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:16px;overflow:hidden;">'
        '<tr><td style="padding:32px 40px 24px;border-bottom:1px solid rgba(255,255,255,0.06);">'
        '<span style="font-size:20px;font-weight:700;color:#fff;">&#x1f6e1; Spectra</span>'
        "</td></tr>"
        '<tr><td style="padding:32px 40px;color:#e2e8f0;font-size:15px;line-height:1.7;">'
        f"{content}"
        "</td></tr>"
        '<tr><td style="padding:24px 40px;border-top:1px solid rgba(255,255,255,0.06);text-align:center;">'
        f'<p style="margin:0;font-size:12px;color:#64748b;">Spectra Security &middot; {unsub_link}</p>'
        "</td></tr>"
        "</table>"
        "</td></tr></table>"
        "</body></html>"
    )
