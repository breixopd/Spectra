"""Manual pentesting helper API endpoints.

Provides checklists, payloads, GTFOBins reference, CVSS calculator,
and report template endpoints.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rate_limit import RateLimits, limiter
from app.core.database import get_async_session
from app.models.user import User
from app.repositories.mission import MissionRepository
from app.services.mission.output_model import (
    get_mission_findings,
    get_mission_summary_dict,
)
from app.services.system.checklists import get_checklist, list_checklists
from app.services.system.cvss import calculate_cvss31
from app.services.system.gtfobins import search_gtfobins
from app.services.system.payloads import get_payloads, list_payload_types
from app.services.system.report_templates import (
    build_report_data,
    list_report_templates,
)
from spectra_api.api.dependencies import check_feature_allowed, check_resource_owner, get_current_active_user
from spectra_common.errors import NotFoundError, ValidationError

logger = logging.getLogger(__name__)

async def require_manual_mode(
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> User:
    await check_feature_allowed(current_user, session, "manual_mode")
    return current_user


router = APIRouter(tags=["Manual Helpers"], dependencies=[Depends(require_manual_mode)])


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
        logger.warning("CVSS calculation failed: %s", e)
        raise HTTPException(status_code=400, detail="Invalid CVSS vector string")


# --- Report Templates ---


@router.get("/reports/templates")
async def api_list_report_templates(
    _current_user: User = Depends(get_current_active_user),
) -> list[dict[str, Any]]:
    """List available report templates."""
    return list_report_templates()


class GenerateReportRequest(BaseModel):
    session_id: str | None = Field(default=None, description="Pentest session ID")
    mission_id: str | None = Field(default=None, description="Mission ID")
    template_id: str | None = Field(default=None, description="Report template ID")

    @model_validator(mode="after")
    def validate_source_and_template(self) -> GenerateReportRequest:
        if bool(self.session_id) == bool(self.mission_id):
            raise ValueError("Provide exactly one of session_id or mission_id")
        if not self.template_id:
            raise ValueError("template_id is required")
        return self


def _build_report_source_from_mission(mission: Any) -> dict[str, Any]:
    summary = get_mission_summary_dict(mission)
    mission_id = str(getattr(mission, "id", ""))
    directive = getattr(mission, "directive", "") or ""

    return {
        "id": mission_id,
        "name": directive or f"Mission {mission_id[:8] or 'report'}",
        "target": getattr(mission, "target", "") or "",
        "findings": get_mission_findings(mission),
        "scope": summary.get("scope") or getattr(mission, "attack_surface", None),
        "tools_used": summary.get("tools_run", []) or [],
        "command_history": getattr(mission, "logs", []) or [],
    }


@router.post("/reports/generate")
@limiter.limit(RateLimits.API_HEAVY)
async def api_generate_report(
    request: Request,
    req: GenerateReportRequest,
    session: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Generate report data from a session or mission using a template."""
    _ = request
    template_id = req.template_id

    try:
        if req.mission_id:
            repo = MissionRepository(session)
            mission = await repo.get_by_id(req.mission_id)
            if not mission:
                raise HTTPException(status_code=404, detail="Mission not found")

            check_resource_owner(mission, _current_user, "mission")
            report_data = build_report_data(_build_report_source_from_mission(mission), template_id)
            report_data["mission_id"] = str(mission.id)
            report_data["source_type"] = "mission"
            return report_data

        from app.services.pentest.session_loader import load_session

        session = await load_session(req.session_id)
        if session.get("owner_id") != str(_current_user.id) and not getattr(_current_user, "is_superuser", False):
            raise HTTPException(status_code=403, detail="Forbidden")
        report_data = build_report_data(session, template_id)
        report_data["source_type"] = "session"
        return report_data
    except (FileNotFoundError, NotFoundError):
        raise HTTPException(status_code=404, detail="Session not found")
    except (ValueError, ValidationError) as e:
        logger.warning("Report generation failed: %s", e)
        raise HTTPException(status_code=400, detail="Report generation failed \u2014 check parameters")
