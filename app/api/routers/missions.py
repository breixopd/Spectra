"""
Mission API Router.

Endpoints for managing security missions.
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    _get_user_plan,
    _is_admin_user,
    check_feature_allowed,
    check_mission_limit,
    check_resource_owner,
    get_current_active_user,
)
from app.api.schemas import MissionResponse, PaginatedResponse, StartMissionRequest
from app.core.database import get_async_session
from app.core.rate_limit import limiter
from app.core.rbac import Permission, require_permission
from app.models.audit_log import AuditEventType
from app.models.user import User
from app.repositories.mission import MissionRepository
from app.services.mission import mission_manager
from app.services.system.audit import log_event as audit_log_event

logger = logging.getLogger(__name__)

from app.core.constants import API_DEFAULT_PAGE_SIZE as DEFAULT_PAGE_SIZE
from app.core.constants import API_MAX_PAGE_SIZE as MAX_PAGE_SIZE

router = APIRouter(prefix="/missions", tags=["Missions"])


class SteerMissionRequest(BaseModel):
    """Schema for steering a mission."""

    action: str = Field(
        ..., description="Steering action: skip_phase, prioritize_target, focus_vuln"
    )
    phase: str | None = Field(None, description="Phase to skip (for skip_phase action)")
    target: str | None = Field(None, description="Target to prioritize")
    vulnerability: str | None = Field(None, description="Vulnerability to focus on")


@router.get("/presets")
async def get_scan_presets(
    _current_user: User = Depends(get_current_active_user),
) -> list[dict[str, Any]]:
    """Get available scan presets."""
    from app.services.mission.presets import SCAN_PRESETS
    return SCAN_PRESETS


@router.get("/adversary-playbooks")
async def get_adversary_playbooks(
    _current_user: User = Depends(get_current_active_user),
) -> list[dict[str, Any]]:
    """List available adversary simulation playbooks."""
    from app.services.ai.adversary_playbooks import list_adversary_playbooks

    return list_adversary_playbooks()


@router.get("/adversary-playbooks/{playbook_id}")
async def get_adversary_playbook_detail(
    playbook_id: str,
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Get full details of an adversary playbook."""
    from app.services.ai.adversary_playbooks import get_adversary_playbook

    pb = get_adversary_playbook(playbook_id)
    if not pb:
        raise HTTPException(status_code=404, detail="Playbook not found")
    return pb.model_dump()


@router.get("/exploit-chains")
async def get_exploit_chains(
    _current_user: User = Depends(get_current_active_user),
) -> list[dict[str, Any]]:
    """List available exploit chains (builtin + custom)."""
    from app.services.mission.chain_builder import get_builtin_chains, load_custom_chains

    builtin = [c.model_dump() for c in get_builtin_chains()]
    custom = [c.model_dump() for c in load_custom_chains()]
    return builtin + custom


class CreateChainRequest(BaseModel):
    """Schema for creating a custom exploit chain."""

    name: str = Field(..., max_length=200)
    description: str = Field("", max_length=1000)
    stages: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/exploit-chains")
async def create_exploit_chain(
    chain_in: CreateChainRequest,
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Create a custom exploit chain."""
    from app.services.mission.chain_builder import ChainBuilder, save_custom_chain

    chain = ChainBuilder.create_chain(chain_in.name, chain_in.stages)
    chain.description = chain_in.description

    warnings = ChainBuilder.validate_chain(chain)
    save_custom_chain(chain)

    return {"chain": chain.model_dump(), "warnings": warnings}


@router.get("/attack-summary")
async def get_attack_coverage(
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Get MITRE ATT&CK technique coverage from all recent missions."""
    from app.services.ai.mitre_attack import get_attack_summary

    # Get recent mission findings from memory
    try:
        from app.services.ai.memory import get_memory

        memory = get_memory()
        findings = []
        for lesson in memory.tool_lessons[-50:]:
            findings.append(
                {"tool_name": lesson.tool_id, "source": "tool_execution"}
            )
        return get_attack_summary(findings)
    except Exception:
        return {"tactics": {}, "total_techniques": 0}


@router.post(
    "",
    response_model=MissionResponse,
    summary="Start mission",
    description="Create and start a new security assessment mission against specified targets.",
)
@limiter.limit("5/minute")
async def start_mission(
    request: Request,
    response: Response,
    mission_request: StartMissionRequest,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = require_permission(Permission.MANAGE_MISSIONS),
) -> MissionResponse:
    """Start a new mission.

    Rate limited to 5 missions per minute per user.
    """
    await check_mission_limit(_current_user, db)
    await check_feature_allowed(_current_user, db, "autonomous_mode")

    mission_id = await mission_manager.start_mission(
        mission_request.target,
        mission_request.directive,
        requirements=mission_request.requirements,
        vpn_config=mission_request.vpn_config,
        user_id=str(_current_user.id),
        requires_approval=mission_request.requires_approval,
    )
    mission = await mission_manager.get_mission(mission_id)

    if not mission:
        raise HTTPException(status_code=500, detail="Failed to create mission")

    # Audit log
    await audit_log_event(
        db,
        AuditEventType.MISSION_LAUNCHED,
        user_id=str(_current_user.id),
        details={"mission_id": mission_id, "target": mission_request.target},
        request=request,
    )

    current_phase = None
    if mission.plan and hasattr(mission.plan, "current_phase"):
        current_phase = (
            mission.plan.current_phase.value
            if hasattr(mission.plan.current_phase, "value")
            else str(mission.plan.current_phase)
        )

    return MissionResponse(
        id=mission.id,
        target=mission.target,
        status=mission.status,
        current_phase=current_phase,
        logs=mission.logs,
        directive=mission.directive,
        findings=mission.findings,
        findings_count=len(mission.findings),
        tools_run=mission.tools_run or [],
        tool_executions=getattr(mission, "tool_executions", []),
        report_path=getattr(mission, "report_path", None),
        attack_surface=mission.attack_surface.get_summary()
        if mission.attack_surface
        else None,
    )


@router.get(
    "",
    response_model=PaginatedResponse,
    summary="List missions",
    description="Retrieve all missions for the authenticated user with optional status and target filters.",
)
async def list_missions(
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="Max records to return",
    ),
    status_filter: str | None = Query(None, alias="status", description="Comma-separated statuses"),
    target: str | None = Query(None, description="Filter by target (partial match)"),
    date_from: str | None = Query(None, description="ISO date lower bound"),
    date_to: str | None = Query(None, description="ISO date upper bound"),
    search: str | None = Query(None, max_length=200, description="Search in directive"),
    sort_by: str | None = Query(None, pattern="^(created_at|status|target)$", description="Sort field"),
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> PaginatedResponse:
    """List all missions (active and historical).

    Supports filtering by status, target, date range, and free-text search.
    Pagination: max 100 items per page.
    """
    from datetime import datetime as dt

    from sqlalchemy import func, select

    from app.models.mission import Mission

    base = select(Mission)

    # User isolation: non-superusers see only their own missions
    if not _current_user.is_superuser:
        base = base.where(Mission.user_id == str(_current_user.id))

    if status_filter:
        statuses = [s.strip() for s in status_filter.split(",") if s.strip()]
        if statuses:
            base = base.where(Mission.status.in_(statuses))

    if target:
        base = base.where(Mission.target.contains(target))

    if date_from:
        try:
            from_dt = dt.fromisoformat(date_from)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid date_from format: {date_from}. Use ISO 8601.")
        base = base.where(Mission.created_at >= from_dt)

    if date_to:
        try:
            to_dt = dt.fromisoformat(date_to)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid date_to format: {date_to}. Use ISO 8601.")
        base = base.where(Mission.created_at <= to_dt)

    if search:
        base = base.where(Mission.directive.contains(search))

    # Count total matching
    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    # Apply ordering
    if sort_by == "status":
        base = base.order_by(Mission.status)
    elif sort_by == "target":
        base = base.order_by(Mission.target)
    else:
        base = base.order_by(Mission.created_at.desc())

    skip = (page - 1) * per_page
    stmt = base.offset(skip).limit(min(per_page, MAX_PAGE_SIZE))
    result = await db.execute(stmt)
    missions = result.scalars().all()

    items = [
        MissionResponse(
            id=m.id,
            target=m.target,
            status=m.status,
            current_phase=m.summary.get("current_phase") if m.summary else None,
            logs=m.logs or [],
            directive=m.directive,
            findings=m.summary.get("findings", []) if m.summary else [],
        )
        for m in missions
    ]
    return PaginatedResponse(items=items, total=total, page=page, per_page=per_page)


@router.get("/{mission_id}/report/pdf")
async def download_pdf_report(
    mission_id: str,
    session: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> Response:
    """Download mission report as PDF."""
    from fastapi.responses import Response as FastAPIResponse

    from app.services.mission.report_generator import generate_pdf_report

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

    mission_data = {
        "id": mission.id,
        "target": mission.target,
        "status": mission.status,
        "findings": mission.summary.get("findings", []) if mission.summary else [],
        "logs": mission.logs or [],
        "tools_run": mission.summary.get("tools_run", []) if mission.summary else [],
        "attack_surface": mission.attack_surface or {},
    }

    try:
        pdf_bytes = generate_pdf_report(mission_data)
    except ImportError:
        raise HTTPException(status_code=501, detail="PDF export requires xhtml2pdf")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return FastAPIResponse(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=spectra_report_{mission_id[:8]}.pdf"
        },
    )


@router.get("/{mission_id}/export/json")
async def export_mission_json(
    mission_id: str,
    encrypted: bool = Query(False),
    password: str | None = Header(None, alias="X-Export-Password"),
    session: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> Response:
    """Export mission + findings as a JSON file."""
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

    summary = mission.summary or {}
    export_data = {
        "mission": {
            "id": mission.id,
            "target": mission.target,
            "status": mission.status,
            "directive": mission.directive,
            "created_at": mission.created_at.isoformat() if mission.created_at else None,
        },
        "findings": summary.get("findings", []),
        "tools_used": summary.get("tools_run", []),
        "timeline": summary.get("timeline", []),
        "attack_surface": mission.attack_surface or {},
    }

    payload = json.dumps(export_data, indent=2, default=str).encode()

    if encrypted:
        if not password:
            raise HTTPException(status_code=400, detail="X-Export-Password header required when encrypted=true")
        from app.core.encryption import encrypt_data_with_password
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


@router.get("/{mission_id}/findings")
async def get_mission_findings(
    mission_id: str,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> list[dict[str, str]]:
    """Get all findings for a specific mission."""
    repo = MissionRepository(db)
    mission = await repo.get_by_id(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    check_resource_owner(mission, _current_user, "mission")
    raw_findings = mission.summary.get("findings", []) if mission.summary else []
    return [
        {
            "id": str(i),
            "title": f.get("title", "Untitled"),
            "severity": f.get("severity", "info"),
            "status": f.get("status", "potential"),
            "description": f.get("description", ""),
            "tool_source": f.get("tool_source", f.get("tool", "")),
            "created_at": f.get("created_at", ""),
        }
        for i, f in enumerate(raw_findings)
        if isinstance(f, dict)
    ]


@router.get(
    "/{mission_id}",
    response_model=MissionResponse,
    summary="Get mission",
    description="Retrieve a single mission by its ID, including current phase, findings, and tool executions.",
)
async def get_mission(
    mission_id: str,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> MissionResponse:
    """Get mission status."""
    # Try active missions first
    mission = await mission_manager.get_mission(mission_id)

    if mission:
        check_resource_owner(mission, _current_user, "mission")
        current_phase = None
        if mission.plan and hasattr(mission.plan, "current_phase"):
            current_phase = (
                mission.plan.current_phase.value
                if hasattr(mission.plan.current_phase, "value")
                else str(mission.plan.current_phase)
            )
        return MissionResponse(
            id=mission.id,
            target=mission.target,
            status=mission.status,
            current_phase=current_phase,
            logs=mission.logs,
            directive=mission.directive,
            findings=mission.findings,
            findings_count=len(mission.findings),
            tools_run=mission.tools_run or [],
            tool_executions=getattr(mission, "tool_executions", []),
            report_path=getattr(mission, "report_path", None),
            attack_surface=mission.attack_surface.get_summary()
            if mission.attack_surface
            else None,
        )

    # Try DB
    repo = MissionRepository(db)
    db_mission = await repo.get_by_id(mission_id)

    if not db_mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    check_resource_owner(db_mission, _current_user, "mission")

    return MissionResponse(
        id=db_mission.id,
        target=db_mission.target,
        status=db_mission.status,
        current_phase=db_mission.summary.get("current_phase")
        if db_mission.summary
        else None,
        logs=db_mission.logs or [],
        directive=db_mission.directive,
        findings=db_mission.summary.get("findings", []) if db_mission.summary else [],
    )


@router.delete(
    "/{mission_id}",
    summary="Delete mission",
    description="Permanently delete a completed or failed mission and its associated storage data.",
)
async def delete_mission(
    mission_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = require_permission(Permission.MANAGE_MISSIONS),
) -> dict[str, str]:
    """Delete a mission and clean up associated filesystem data."""
    repo = MissionRepository(db)
    mission = await repo.get_by_id(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    check_resource_owner(mission, _current_user, "mission")

    active_statuses = {
        "created", "initializing", "scoping", "planning", "running",
        "scanning", "analyzing", "executing", "exploiting", "paused",
    }
    if mission.status in active_statuses:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete an active mission. Stop it first.",
        )

    await repo.delete(mission_id)
    await db.commit()

    # Clean up storage data
    from app.core.config import settings
    from app.services.storage import get_storage_service

    storage = get_storage_service()
    keys = await storage.list_objects(settings.S3_BUCKET_MISSIONS, prefix=f"{mission_id}/")
    for key in keys:
        await storage.delete(settings.S3_BUCKET_MISSIONS, key)

    await audit_log_event(
        db,
        AuditEventType.MISSION_DELETED,
        user_id=str(_current_user.id),
        details={"mission_id": mission_id, "target": mission.target},
        request=request,
    )

    return {"status": "deleted", "mission_id": mission_id}


@router.post(
    "/{mission_id}/stop",
    summary="Stop mission",
    description="Stop a running mission. The mission must be in an active state.",
)
@limiter.limit("10/minute")
async def stop_mission(
    request: Request,
    response: Response,
    mission_id: str,
    _current_user: User = require_permission(Permission.MANAGE_MISSIONS),
) -> dict[str, str]:
    """Stop a running mission. Requires superuser privileges."""
    active = await mission_manager.get_mission(mission_id)
    if active:
        check_resource_owner(active, _current_user, "mission")
    result = await mission_manager.stop_mission(mission_id)
    if not result:
        raise HTTPException(status_code=404, detail="Mission not found or not active")
    return {"message": "Mission stopping"}


@router.post(
    "/{mission_id}/pause",
    summary="Pause mission",
    description="Pause a running mission. It can be resumed later.",
)
@limiter.limit("10/minute")
async def pause_mission(
    request: Request,
    response: Response,
    mission_id: str,
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, str]:
    """Pause a running mission."""
    active = await mission_manager.get_mission(mission_id)
    if active:
        check_resource_owner(active, _current_user, "mission")
    result = await mission_manager.pause_mission(mission_id)
    if not result:
        raise HTTPException(status_code=404, detail="Mission not found or not active")
    return {"message": "Mission paused"}


@router.post(
    "/{mission_id}/resume",
    summary="Resume mission",
    description="Resume a previously paused mission from where it left off.",
)
@limiter.limit("10/minute")
async def resume_mission(
    request: Request,
    response: Response,
    mission_id: str,
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, str]:
    """Resume a paused mission."""
    active = await mission_manager.get_mission(mission_id)
    if active:
        check_resource_owner(active, _current_user, "mission")
    result = await mission_manager.resume_mission(mission_id)
    if not result:
        raise HTTPException(status_code=404, detail="Mission not found or not active")
    return {"message": "Mission resumed"}


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
    from app.services.mission.target_diff import compare_missions, generate_diff_report

    repo = MissionRepository(db)

    old_db = await repo.get_by_id(mission_id)
    if not old_db:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")
    check_resource_owner(old_db, _current_user, "mission")

    new_db = await repo.get_by_id(other_mission_id)
    if not new_db:
        raise HTTPException(
            status_code=404, detail=f"Mission {other_mission_id} not found"
        )
    check_resource_owner(new_db, _current_user, "mission")

    old_dict = {
        "id": old_db.id,
        "target": old_db.target,
        "status": old_db.status,
        "findings": (old_db.summary or {}).get("findings", []),
        "attack_surface": old_db.attack_surface or {},
        "summary": old_db.summary or {},
    }
    new_dict = {
        "id": new_db.id,
        "target": new_db.target,
        "status": new_db.status,
        "findings": (new_db.summary or {}).get("findings", []),
        "attack_surface": new_db.attack_surface or {},
        "summary": new_db.summary or {},
    }

    diff = compare_missions(old_dict, new_dict)
    report = generate_diff_report(diff)

    return {
        "old_mission_id": mission_id,
        "new_mission_id": other_mission_id,
        "diff": diff,
        "report": report,
    }


@router.post("/{mission_id}/steer")
@limiter.limit("30/minute")
async def steer_mission(
    request: Request,
    response: Response,
    mission_id: str,
    steer_request: SteerMissionRequest,
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """
    Steer a running mission.

    Allows human-in-the-loop control:
    - skip_phase: Skip a specific phase (e.g., enumeration)
    - prioritize_target: Focus on a specific target/service
    - focus_vuln: Prioritize a specific vulnerability
    """

    try:
        active = await mission_manager.get_mission(mission_id)
        if active:
            check_resource_owner(active, _current_user, "mission")
        result = await mission_manager.steer_mission(
            mission_id=mission_id,
            action=steer_request.action,
            phase=steer_request.phase,
            target=steer_request.target,
            vulnerability=steer_request.vulnerability,
        )
        return result
    except ValueError as e:
        logger.error("Mission steering error: %s", e, exc_info=True)
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail="Mission or target not found")
        raise HTTPException(status_code=400, detail="Invalid steering request")


@router.get("/{mission_id}/task-tree")
async def get_task_tree(
    mission_id: str,
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Get the task tree for a mission."""
    mission = await mission_manager.get_mission(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    check_resource_owner(mission, _current_user, "mission")
    return mission.task_tree.to_dict()


@router.get("/{mission_id}/progress")
async def get_mission_progress(
    mission_id: str,
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Get estimated mission progress."""
    mission = await mission_manager.get_mission(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    check_resource_owner(mission, _current_user, "mission")
    return mission.get_progress()


class ApproveActionRequest(BaseModel):
    """Schema for approving/rejecting a pending mission action."""

    action_id: str = Field(..., description="ID of the action to approve or reject")
    approved: bool = Field(default=True, description="Whether to approve the action")


@router.post("/{mission_id}/approve")
async def approve_action(
    mission_id: str,
    body: ApproveActionRequest,
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, str | bool]:
    """Approve or reject a pending action in a mission that requires approval."""
    mission = await mission_manager.get_mission(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    check_resource_owner(mission, _current_user, "mission")

    if not getattr(mission, "requires_approval", False):
        raise HTTPException(status_code=400, detail="Mission does not require approval")

    from app.core.websocket import manager

    await manager.broadcast_to_room_json(f"mission:{mission_id}", {
        "type": "action_approval",
        "action_id": body.action_id,
        "approved": body.approved,
    })
    return {"status": "approval_sent", "action_id": body.action_id, "approved": body.approved}
