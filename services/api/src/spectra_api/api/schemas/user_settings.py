"""Schemas for user settings / preferences API."""

import ipaddress
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, field_validator


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
    prefer_mission_approval: bool = False
    default_scan_mode: str = "autonomous"
    default_report_format: str = "pdf"
    # UI
    timezone: str = "UTC"
    # Training data
    share_training_data: bool = False


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
    prefer_mission_approval: bool | None = None
    default_scan_mode: Literal["autonomous", "guided", "manual"] | None = None
    default_report_format: Literal["pdf", "html", "json"] | None = None
    # UI
    timezone: str | None = None
    # Training data
    share_training_data: bool | None = None

    @field_validator("llm_api_base_url", "embedding_api_base_url", "webhook_url", mode="before")
    @classmethod
    def validate_url_not_internal(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("URL must use http or https scheme")
        hostname = parsed.hostname or ""
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise ValueError("URL must not point to internal/private IP addresses")
        except ValueError as e:
            if "internal" in str(e) or "private" in str(e):
                raise
            # Not an IP — it's a hostname, check for obvious internal names
            blocked_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "metadata.google.internal", "169.254.169.254"}
            if hostname.lower() in blocked_hosts:
                raise ValueError("URL must not point to internal services")
        return v
