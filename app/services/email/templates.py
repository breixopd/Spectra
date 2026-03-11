"""Email template definitions for common platform emails."""

from __future__ import annotations

WELCOME = """
<h1>Welcome to Spectra</h1>
<p>Hi {username},</p>
<p>Your account has been created. You can log in at
<a href="{login_url}">{login_url}</a>.</p>
"""

PASSWORD_RESET = """
<h1>Password Reset</h1>
<p>Hi {username},</p>
<p>Click the link below to reset your password. This link expires in 1 hour.</p>
<p><a href="{reset_url}">{reset_url}</a></p>
<p>If you didn't request this, you can safely ignore this email.</p>
"""

MISSION_COMPLETE = """
<h1>Mission Complete</h1>
<p>Hi {username},</p>
<p>Your mission against <strong>{target}</strong> has finished.</p>
<ul>
  <li>Status: {status}</li>
  <li>Findings: {finding_count}</li>
</ul>
<p><a href="{report_url}">View full report</a></p>
"""

ALERT = """
<h1>Security Alert</h1>
<p>Hi {username},</p>
<p><strong>{alert_title}</strong></p>
<p>{alert_message}</p>
"""

TEMPLATES: dict[str, str] = {
    "welcome": WELCOME,
    "password_reset": PASSWORD_RESET,
    "mission_complete": MISSION_COMPLETE,
    "alert": ALERT,
}
