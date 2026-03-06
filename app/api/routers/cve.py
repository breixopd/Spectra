"""CVE Intelligence API Router.

Exposes CVE lookup capabilities to the UI for manual pentest workflows.
"""

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_current_active_user
from app.models.user import User
from app.services.ai.cve_intel import lookup_cves_live

router = APIRouter(prefix="/cve", tags=["CVE Intelligence"])


@router.get("/lookup")
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
        "cves": cves[:50],
        "total": len(cves),
        "query": {"product": product, "version": version, "service": service, "keyword": keyword},
    }
