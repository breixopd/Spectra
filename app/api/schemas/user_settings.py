"""Schemas for user settings / preferences API."""

from pydantic import BaseModel


class UserSettingsResponse(BaseModel):
    """Read-only view of user preferences. API keys are masked."""

    # BYOK (keys masked)
    llm_api_key_configured: bool = False
    llm_api_base_url: str | None = None
    llm_model: str | None = None
    embedding_api_key_configured: bool = False
    embedding_api_base_url: str | None = None
    embedding_model: str | None = None
    # Notifications
    email_notifications: bool = True
    webhook_url: str | None = None
    notify_on_mission_complete: bool = True
    notify_on_critical_finding: bool = True
    # Mission defaults
    default_scan_mode: str = "autonomous"
    default_report_format: str = "pdf"
    # UI
    timezone: str = "UTC"


class UserSettingsUpdate(BaseModel):
    """Partial update payload for user preferences."""

    # BYOK fields — only writable if plan allows
    llm_api_key: str | None = None
    llm_api_base_url: str | None = None
    llm_model: str | None = None
    embedding_api_key: str | None = None
    embedding_api_base_url: str | None = None
    embedding_model: str | None = None
    # Notifications
    email_notifications: bool | None = None
    webhook_url: str | None = None
    notify_on_mission_complete: bool | None = None
    notify_on_critical_finding: bool | None = None
    # Mission defaults
    default_scan_mode: str | None = None
    default_report_format: str | None = None
    # UI
    timezone: str | None = None
