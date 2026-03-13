"""CVE Intelligence API Router.

Exposes CVE lookup capabilities to the UI for manual pentest workflows.
"""

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.api.dependencies import get_current_active_user
from app.api.schemas.cve import (
    CVEEnrichedResponse,
    CVEExploitsResponse,
    CVELookupResponse,
    SearchExploitResponse,
)
from app.core.constants import CVE_RESULTS_LIMIT
from app.models.user import User

_CVE_PATTERN = re.compile(r"^CVE-\d{4}-\d{4,}$")
from app.services.ai.cve_intel import (
    get_metasploit_modules,
    lookup_cves_live,
    search_exploitdb,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cve", tags=["CVE Intelligence"])


@router.get("/lookup", response_model=CVELookupResponse)
async def cve_lookup(
    product: str | None = Query(default=None, max_length=200, description="Product name (e.g., Apache)"),
    version: str | None = Query(default=None, max_length=50, description="Version (e.g., 2.4.49)"),
    service: str | None = Query(default=None, max_length=100, description="Service name (e.g., http)"),
    keyword: str | None = Query(default=None, max_length=200, description="Free-text search keyword"),
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Look up known CVEs for a product/version/service.

    Uses built-in CVE database with optional live NVD API enrichment.
    """
    if not any([product, version, service, keyword]):
        return {"cves": [], "query": {}, "message": "Provide at least one search parameter."}

    effective_product = product or keyword
    cves = await lookup_cves_live(
        product=effective_product,
        version=version,
        service=service,
    )

    return {
        "cves": cves[:CVE_RESULTS_LIMIT],
        "total": len(cves),
        "query": {"product": product, "version": version, "service": service, "keyword": keyword},
    }


@router.get("/{cve_id}/exploits", response_model=CVEExploitsResponse)
async def get_cve_exploits(
    cve_id: str = Path(..., pattern=r"^CVE-\d{4}-\d{4,}$"),
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Get available exploit modules for a specific CVE."""
    modules = get_metasploit_modules(cve_id)
    return {
        "cve_id": cve_id,
        "exploit_available": len(modules) > 0,
        "metasploit_modules": modules,
        "total": len(modules),
    }


@router.get("/{cve_id}/enriched", response_model=CVEEnrichedResponse)
async def get_cve_enriched(
    cve_id: str = Path(..., pattern=r"^CVE-\d{4}-\d{4,}$"),
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Get unified exploit intelligence for a CVE (exploits + EPSS + KEV)."""
    from app.services.ai.exploit_db import get_exploit_db

    db = get_exploit_db()
    return await db.enrich(cve_id)


@router.get("/searchsploit/{query:path}", response_model=SearchExploitResponse)
async def search_exploitdb_endpoint(
    query: str,
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Search ExploitDB for exploits matching a query."""
    if len(query) > 200:
        raise HTTPException(status_code=422, detail="Query too long (max 200 chars)")
    results = await search_exploitdb(query)
    msf_matches = get_metasploit_modules(query.upper())
    return {
        "query": query,
        "exploitdb_results": results,
        "metasploit_modules": msf_matches,
        "total": len(results) + len(msf_matches),
    }
