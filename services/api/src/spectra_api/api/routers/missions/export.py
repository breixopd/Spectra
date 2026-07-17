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
from spectra_mission.output_model import (
    get_mission_findings as get_mission_output_findings,
)
from spectra_mission.output_model import (
    get_mission_summary_dict,
)
from spectra_persistence.database import get_async_session
from spectra_persistence.models.audit_log import AuditEventType
from spectra_persistence.models.user import User
from spectra_persistence.repositories.mission import MissionRepository
from spectra_system.audit import log_event as audit_log_event

logger = logging.getLogger(__name__)

router = APIRouter()


def _selected_mission_findings(mission: Any, finding_ids: list[str] | None) -> list[dict[str, Any]]:
    """Return all mission findings or the explicitly selected durable IDs.

    IDs are checked against the mission's normalized output so a stale report-builder
    tab cannot silently produce a report different from the selection the operator saw.
    """
    findings = get_mission_output_findings(mission)
    if finding_ids is None:
        return findings
    if len(finding_ids) > 500:
        raise HTTPException(status_code=422, detail="A report can include at most 500 findings")

    selected = set(finding_ids)
    available = {str(finding["id"]) for finding in findings}
    unknown_ids = selected - available
    if unknown_ids:
        raise HTTPException(status_code=422, detail="One or more selected findings no longer belong to this mission")
    return [finding for finding in findings if str(finding["id"]) in selected]


@router.get("/{mission_id}/report/pdf")
async def download_pdf_report(
    request: Request,
    mission_id: str,
    finding_id: list[str] | None = Query(default=None, description="Durable mission finding IDs to include"),
    session: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> Response:
    """Download mission report as PDF."""
    validate_uuid_param(mission_id, "mission_id")
    from fastapi.responses import Response as FastAPIResponse

    from spectra_mission.report_generator import generate_pdf_report

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
        "findings": _selected_mission_findings(mission, finding_id),
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
        details={
            "action": "mission_exported",
            "mission_id": str(mission_id),
            "format": "pdf",
            "selected_finding_count": len(finding_id) if finding_id is not None else None,
        },
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
    finding_id: list[str] | None = Query(default=None, description="Durable mission finding IDs to include"),
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
        "findings": _selected_mission_findings(mission, finding_id),
        "tools_used": summary.get("tools_run", []),
        "timeline": summary.get("timeline", []),
        "attack_surface": mission.attack_surface or {},
    }

    await audit_log_event(
        session,
        AuditEventType.DATA_EXPORTED,
        user_id=str(_current_user.id),
        details={
            "action": "mission_exported",
            "mission_id": str(mission_id),
            "format": "json",
            "selected_finding_count": len(finding_id) if finding_id is not None else None,
        },
        request=request,
    )

    payload = json.dumps(export_data, indent=2, default=str).encode()

    if encrypted:
        if not password:
            raise HTTPException(status_code=400, detail="X-Export-Password header required when encrypted=true")
        from spectra_common.encryption import encrypt_data_with_password

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
    from spectra_mission.target_diff import compare_missions, generate_diff_report

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
