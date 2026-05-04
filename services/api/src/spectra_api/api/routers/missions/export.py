"""Mission export endpoints — PDF report, JSON export, diff."""

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_api.api.dependencies import (
    _get_user_plan,
    _is_admin_user,
    check_resource_owner,
    get_current_active_user,
    validate_uuid_param,
)
from spectra_platform.core.database import get_async_session
from spectra_platform.models.audit_log import AuditEventType
from spectra_platform.models.user import User
from spectra_platform.repositories.mission import MissionRepository
from spectra_platform.services.mission.output_model import (
    get_mission_findings as get_mission_output_findings,
)
from spectra_platform.services.mission.output_model import (
    get_mission_summary_dict,
)
from spectra_platform.services.system.audit import log_event as audit_log_event

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{mission_id}/report/pdf")
async def download_pdf_report(
    request: Request,
    mission_id: str,
    session: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> Response:
    """Download mission report as PDF."""
    validate_uuid_param(mission_id, "mission_id")
    from fastapi.responses import Response as FastAPIResponse

    from spectra_platform.services.mission.report_generator import generate_pdf_report

    repo = MissionRepository(session)
    mission = await repo.get_by_id(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    check_resource_owner(mission, _current_user, "mission")

    # Check plan allows PDF export
    if not _is_admin_user(_current_user):
        plan = await _get_user_plan(_current_user, session)
        if plan and plan.features:
            allowed = plan.features.get("report_export", ["json", "pdf", "html"])
            if isinstance(allowed, list) and "pdf" not in allowed:
                raise HTTPException(403, "PDF export not available on your plan")

    summary = get_mission_summary_dict(mission)
    mission_data = {
        "id": mission.id,
        "target": mission.target,
        "status": mission.status,
        "findings": get_mission_output_findings(mission),
        "logs": mission.logs or [],
        "tools_run": summary.get("tools_run", []),
        "attack_surface": mission.attack_surface or {},
    }

    try:
        pdf_bytes = generate_pdf_report(mission_data)
    except ImportError:
        raise HTTPException(status_code=501, detail="PDF export requires xhtml2pdf")
    except RuntimeError as e:
        logger.error("PDF report generation failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Report generation failed")

    await audit_log_event(
        session,
        AuditEventType.DATA_EXPORTED,
        user_id=str(_current_user.id),
        details={"action": "mission_exported", "mission_id": str(mission_id), "format": "pdf"},
        request=request,
    )

    return FastAPIResponse(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=spectra_report_{mission_id[:8]}.pdf"},
    )


@router.get("/{mission_id}/export/json")
async def export_mission_json(
    request: Request,
    mission_id: str,
    encrypted: bool = Query(False),
    password: str | None = Header(None, alias="X-Export-Password"),
    session: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> Response:
    """Export mission + findings as a JSON file."""
    validate_uuid_param(mission_id, "mission_id")
    from fastapi.responses import Response as FastAPIResponse

    repo = MissionRepository(session)
    mission = await repo.get_by_id(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    check_resource_owner(mission, _current_user, "mission")

    # Check plan allows JSON export
    if not _is_admin_user(_current_user):
        plan = await _get_user_plan(_current_user, session)
        if plan and plan.features:
            allowed = plan.features.get("report_export", ["json", "pdf", "html"])
            if isinstance(allowed, list) and "json" not in allowed:
                raise HTTPException(403, "JSON export not available on your plan")

    summary = get_mission_summary_dict(mission)
    export_data = {
        "mission": {
            "id": mission.id,
            "target": mission.target,
            "status": mission.status,
            "directive": mission.directive,
            "created_at": mission.created_at.isoformat() if mission.created_at else None,
        },
        "findings": get_mission_output_findings(mission),
        "tools_used": summary.get("tools_run", []),
        "timeline": summary.get("timeline", []),
        "attack_surface": mission.attack_surface or {},
    }

    await audit_log_event(
        session,
        AuditEventType.DATA_EXPORTED,
        user_id=str(_current_user.id),
        details={"action": "mission_exported", "mission_id": str(mission_id), "format": "json"},
        request=request,
    )

    payload = json.dumps(export_data, indent=2, default=str).encode()

    if encrypted:
        if not password:
            raise HTTPException(status_code=400, detail="X-Export-Password header required when encrypted=true")
        from spectra_platform.auth.encryption import encrypt_data_with_password

        payload = encrypt_data_with_password(payload, password)
        return FastAPIResponse(
            content=payload,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename=spectra_export_{mission_id[:8]}.json.enc"},
        )

    return FastAPIResponse(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=spectra_export_{mission_id[:8]}.json"},
    )


@router.get("/{mission_id}/diff/{other_mission_id}")
async def diff_missions(
    mission_id: str,
    other_mission_id: str,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Compare two missions and return a structured diff.

    Returns changed services, findings, and vulnerabilities between
    the *old* mission (``mission_id``) and the *new* mission
    (``other_mission_id``).
    """
    validate_uuid_param(mission_id, "mission_id")
    validate_uuid_param(other_mission_id, "other_mission_id")
    from spectra_platform.services.mission.target_diff import compare_missions, generate_diff_report

    repo = MissionRepository(db)

    old_db = await repo.get_by_id(mission_id)
    if not old_db:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")
    check_resource_owner(old_db, _current_user, "mission")

    new_db = await repo.get_by_id(other_mission_id)
    if not new_db:
        raise HTTPException(status_code=404, detail=f"Mission {other_mission_id} not found")
    check_resource_owner(new_db, _current_user, "mission")

    old_dict = {
        "id": old_db.id,
        "target": old_db.target,
        "status": old_db.status,
        "findings": get_mission_output_findings(old_db),
        "attack_surface": old_db.attack_surface or {},
        "summary": get_mission_summary_dict(old_db),
    }
    new_dict = {
        "id": new_db.id,
        "target": new_db.target,
        "status": new_db.status,
        "findings": get_mission_output_findings(new_db),
        "attack_surface": new_db.attack_surface or {},
        "summary": get_mission_summary_dict(new_db),
    }

    diff = compare_missions(old_dict, new_dict)
    report = generate_diff_report(diff)

    return {
        "old_mission_id": mission_id,
        "new_mission_id": other_mission_id,
        "diff": diff,
        "report": report,
    }
