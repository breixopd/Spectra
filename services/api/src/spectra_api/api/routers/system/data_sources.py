"""Data source management endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.core.database import async_session_maker
from app.models.audit_log import AuditEventType
from app.models.user import User
from app.services.system.audit import log_event as audit_log_event
from spectra_api.api.dependencies import get_current_active_user, get_current_superuser

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/data-sources")
async def get_data_source_status(
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Get status of all managed data sources (exploit DB, CVE KB, etc.)."""
    from app.services.exploit_db import get_exploit_db

    db = get_exploit_db()
    return await db.data_status()


@router.post("/data-sources/download")
async def download_data_sources(
    request: Request,
    _current_user: User = Depends(get_current_superuser),
) -> dict[str, Any]:
    """Update all exploit intelligence data sources.

    Refreshes MSF modules, CISA KEV, and the CVE knowledge base.
    """
    from app.services.exploit_db import get_exploit_db

    db = get_exploit_db()

    # Write CVE knowledge base from curated data
    from app.services.exploit_db import CVE_KNOWLEDGE_BASE

    await db._cache_set("cve_knowledge_base", CVE_KNOWLEDGE_BASE)
    kb_count = len(CVE_KNOWLEDGE_BASE)

    # Reload CVE knowledge base in memory
    from app.services.ai.cve_intel import reload_cve_knowledge_base

    await reload_cve_knowledge_base()

    # Download exploit sources
    stats = await db.update()
    stats["cve_kb_entries"] = kb_count

    async with async_session_maker() as session:
        await audit_log_event(
            session,
            AuditEventType.DATA_SOURCES_UPDATED,
            user_id=str(_current_user.id),
            details={"action": "download"},
            request=request,
        )

    return {"success": True, "message": "Data sources updated", "stats": stats}
