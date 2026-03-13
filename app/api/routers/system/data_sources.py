"""Data source management endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends

from app.api.dependencies import get_current_active_user, get_current_superuser
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/data-sources")
async def get_data_source_status(
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Get status of all managed data sources (exploit DB, CVE KB, etc.)."""
    from app.services.ai.exploit_db import get_exploit_db

    db = get_exploit_db()
    return db.data_status()


@router.post("/data-sources/download")
async def download_data_sources(
    _current_user: User = Depends(get_current_superuser),
) -> dict[str, Any]:
    """Update all exploit intelligence data sources.

    Refreshes MSF modules, CISA KEV, and the CVE knowledge base.
    """
    import json as _json
    from pathlib import Path as _Path

    from app.core.constants import EXPLOIT_DB_CACHE_DIR
    from app.services.ai.exploit_db import get_exploit_db

    db = get_exploit_db()

    # Write CVE knowledge base from the update script's data
    try:
        from scripts.update_exploit_db import _CVE_KNOWLEDGE_BASE

        cache_dir = _Path(EXPLOIT_DB_CACHE_DIR)
        cache_dir.mkdir(parents=True, exist_ok=True)
        kb_path = cache_dir / "cve_knowledge_base.json"
        kb_path.write_text(_json.dumps(_CVE_KNOWLEDGE_BASE, indent=2))
        kb_count = len(_CVE_KNOWLEDGE_BASE)
    except Exception as exc:
        logger.warning("Failed to write CVE knowledge base: %s", exc)
        kb_count = 0

    # Reload CVE knowledge base in memory
    from app.services.ai.cve_intel import reload_cve_knowledge_base

    reload_cve_knowledge_base()

    # Download exploit sources
    stats = await db.update()
    stats["cve_kb_entries"] = kb_count

    return {"success": True, "message": "Data sources updated", "stats": stats}
