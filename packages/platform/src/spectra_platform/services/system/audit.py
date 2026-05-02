"""Audit logging service for security events."""

import hashlib
import json
import logging
from typing import Any

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_common.advisory_locks import stable_lock_id
from spectra_platform.models.audit_log import AuditEventType
from spectra_platform.repositories.audit_log import AuditLogRepository

logger = logging.getLogger(__name__)


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
        entry = await repo.create(
            event_type=event_type.value,
            user_id=user_id,
            details=json.dumps(details) if details else None,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # Compute integrity hash chain — advisory lock prevents concurrent
        # inserts from reading the same prev_hash (hash chain race).
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": stable_lock_id("audit_hash_chain")},
        )
        try:
            prev_hash = await repo.get_latest_hash() or "genesis"
        except Exception:
            prev_hash = "genesis"
        timestamp = entry.created_at.isoformat() if entry.created_at else ""
        hash_input = f"{prev_hash}|{entry.event_type}|{entry.user_id}|{entry.details}|{timestamp}"
        entry.integrity_hash = hashlib.sha256(hash_input.encode()).hexdigest()
        entry.previous_hash = prev_hash

        await session.commit()
    except SQLAlchemyError as e:
        logger.error("Failed to write audit log: %s", e)
        await session.rollback()
