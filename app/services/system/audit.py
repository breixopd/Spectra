"""Audit logging service for security events."""

import json
import logging
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditEventType
from app.repositories.audit_log import AuditLogRepository

logger = logging.getLogger("spectra.audit")


async def log_event(
    session: AsyncSession,
    event_type: AuditEventType,
    user_id: str | None = None,
    details: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    """Log a security-relevant event to the audit table."""
    ip_address = None
    user_agent = None
    if request:
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent", "")[:512]

    repo = AuditLogRepository(session)
    try:
        await repo.create(
            event_type=event_type.value,
            user_id=user_id,
            details=json.dumps(details) if details else None,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await session.commit()
    except Exception as e:
        logger.error("Failed to write audit log: %s", e)
        await session.rollback()
