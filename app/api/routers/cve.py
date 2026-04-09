"""CVE Intelligence API Router.

Exposes CVE lookup capabilities to the UI for manual pentest workflows.
"""

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from app.api.dependencies import get_current_active_user
from app.api.schemas.cve import (
    CVEEnrichedResponse,
    CVEExploitsResponse,
    CVELookupResponse,
    SearchExploitResponse,
)
from app.core.constants import CVE_RESULTS_LIMIT
from app.core.rate_limit import RateLimits, limiter
from app.models.user import User

_CVE_PATTERN = re.compile(r"^CVE-\d{4}-\d{4,}$")
_SEARCHSPLOIT_QUERY_PATTERN = re.compile(r"^[a-zA-Z0-9._ -]{1,200}$")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cve", tags=["CVE Intelligence"])


async def _lookup_cves_live(*, product: str | None, version: str | None, service: str | None):
    from app.services.ai.cve_intel import lookup_cves_live

    return await lookup_cves_live(product=product, version=version, service=service)


def _get_metasploit_modules(cve_id: str):
    from app.services.ai.cve_intel import get_metasploit_modules

    return get_metasploit_modules(cve_id)


async def _search_exploitdb(query: str):
    from app.services.ai.cve_intel import search_exploitdb

    return await search_exploitdb(query)


def _validate_searchsploit_query(query: str) -> str:
    if len(query) > 200:
        raise HTTPException(status_code=422, detail="Query too long (max 200 chars)")
    if not _SEARCHSPLOIT_QUERY_PATTERN.fullmatch(query):
        raise HTTPException(status_code=422, detail="Query contains invalid characters")
    return query


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
    cves = await _lookup_cves_live(
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
    modules = _get_metasploit_modules(cve_id)
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
    from app.services.exploit_db import get_exploit_db

    db = get_exploit_db()
    return await db.enrich(cve_id)


@router.get("/searchsploit", response_model=SearchExploitResponse)
@limiter.limit(RateLimits.API_HEAVY)
async def search_exploitdb_endpoint(
    request: Request,
    query: str = Query(..., min_length=1, max_length=200),
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Search ExploitDB for exploits matching a query."""
    _ = request
    validated_query = _validate_searchsploit_query(query)
    results = await _search_exploitdb(validated_query)
    msf_matches = _get_metasploit_modules(validated_query.upper())
    return {
        "query": validated_query,
        "exploitdb_results": results,
        "metasploit_modules": msf_matches,
        "total": len(results) + len(msf_matches),
    }
