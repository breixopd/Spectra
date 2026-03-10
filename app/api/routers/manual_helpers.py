"""Manual pentesting helper API endpoints.

Provides checklists, payloads, GTFOBins reference, CVSS calculator,
and report template endpoints.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.dependencies import get_current_active_user
from app.models.user import User
from app.services.system.checklists import get_checklist, list_checklists
from app.services.system.cvss import calculate_cvss31
from app.services.system.gtfobins import search_gtfobins
from app.services.system.payloads import get_payloads, list_payload_types
from app.services.system.report_templates import (
    generate_report_data,
    list_report_templates,
)

logger = logging.getLogger("spectra.api.manual_helpers")

router = APIRouter(tags=["Manual Helpers"])


# --- Checklists ---


@router.get("/checklists")
async def api_list_checklists(
    _current_user: User = Depends(get_current_active_user),
) -> list[dict[str, str]]:
    """List all available methodology checklists."""
    return list_checklists()


@router.get("/checklists/{checklist_id}")
async def api_get_checklist(
    checklist_id: str,
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Get a full methodology checklist by ID."""
    result = get_checklist(checklist_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Checklist not found")
    return result


# --- Payloads ---


@router.get("/payloads")
async def api_get_payloads(
    type: str = Query(..., description="Payload type: lfi, sqli, xss"),
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Get security testing payloads by type."""
    available = list_payload_types()
    payloads = get_payloads(type)
    if not payloads:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown payload type '{type}'. Available: {available}",
        )
    return {"type": type, "payloads": payloads, "count": len(payloads)}


# --- GTFOBins ---


@router.get("/gtfobins")
async def api_search_gtfobins(
    search: str = Query(default="", description="Binary name substring"),
    function: str | None = Query(default=None, description="Filter by function (shell, suid, sudo, etc.)"),
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Search GTFOBins reference."""
    results = search_gtfobins(query=search, function_filter=function)
    return {"results": results, "count": len(results)}


# --- CVSS Calculator ---


class CVSSRequest(BaseModel):
    vector: str = Field(..., description="CVSS 3.1 vector string")


@router.post("/cvss/calculate")
async def api_calculate_cvss(
    req: CVSSRequest,
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Calculate CVSS 3.1 base score from vector string."""
    try:
        return calculate_cvss31(req.vector)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Report Templates ---


@router.get("/reports/templates")
async def api_list_report_templates(
    _current_user: User = Depends(get_current_active_user),
) -> list[dict[str, Any]]:
    """List available report templates."""
    return list_report_templates()


class GenerateReportRequest(BaseModel):
    session_id: str = Field(..., description="Pentest session ID")
    template_id: str = Field(..., description="Report template ID")


@router.post("/reports/generate")
async def api_generate_report(
    req: GenerateReportRequest,
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Generate report data from a session using a template."""
    from pathlib import Path

    session_path = Path("data/sessions") / f"{req.session_id}.json"
    try:
        return generate_report_data(session_path, req.template_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
