"""Mission core endpoints — CRUD, list, status, presets, playbooks, chains."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    check_feature_allowed,
    check_mission_limit,
    check_resource_owner,
    get_current_active_user,
)
from app.api.schemas import (
    MissionDeleteResponse,
    MissionFindingSummary,
    MissionResponse,
    PaginatedResponse,
    StartMissionRequest,
    StatusResponse,
)
from app.core.constants import API_DEFAULT_PAGE_SIZE as DEFAULT_PAGE_SIZE
from app.core.constants import API_MAX_PAGE_SIZE as MAX_PAGE_SIZE
from app.core.database import get_async_session
from app.core.rate_limit import RateLimits, limiter
from app.core.rbac import Permission, require_permission
from app.models.audit_log import AuditEventType
from app.models.user import User
from app.repositories.mission import MissionRepository
from app.services.mission import mission_manager
from app.services.mission.output_model import (
    get_mission_finding_counts,
    get_mission_summary_dict,
)
from app.services.mission.output_model import (
    get_mission_findings as get_mission_output_findings,
)
from app.services.system.audit import log_event as audit_log_event

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateChainRequest(BaseModel):
    """Schema for creating a custom exploit chain."""

    name: str = Field(..., max_length=200)
    description: str = Field("", max_length=1000)
    stages: list[dict[str, Any]] = Field(default_factory=list)


@router.get("/presets", response_model=None)
async def get_scan_presets(
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, dict[str, Any]]:
    """Get available scan presets."""
    from app.services.mission.presets import SCAN_PRESETS

    return SCAN_PRESETS


@router.get("/summary", tags=["Missions"])
async def get_missions_summary(
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    """Get aggregated mission summary with finding counts — single query, no N+1."""
    from sqlalchemy import select

    from app.models.mission import Mission

    stmt = select(Mission).order_by(Mission.created_at.desc())

    if not _current_user.is_superuser:
        stmt = stmt.where(Mission.user_id == str(_current_user.id))

    result = await db.execute(stmt)
    db_missions = result.scalars().all()

    missions = []
    totals = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0, "total": 0}

    for m in db_missions:
        counts = get_mission_finding_counts(m)

        missions.append(
            {
                "id": str(m.id),
                "target": m.target,
                "directive": m.directive,
                "status": m.status,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "updated_at": m.updated_at.isoformat() if m.updated_at else None,
                "findings": counts,
            }
        )
        for sev in ("critical", "high", "medium", "low", "info"):
            totals[sev] += counts[sev]
        totals["total"] += counts["total"]

    return {"missions": missions, "totals": totals, "count": len(missions)}


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

        memory = get_memory(str(_current_user.id))
        findings = []
        for lesson in memory.tool_lessons[-50:]:
            findings.append({"tool_name": lesson.tool_id, "source": "tool_execution"})
        return get_attack_summary(findings)
    except (OSError, RuntimeError, ValueError):
        return {"tactics": {}, "total_techniques": 0}


@router.post(
    "",
    response_model=MissionResponse,
    summary="Start mission",
    description="Create and start a new security assessment mission against specified targets.",
)
@limiter.limit(RateLimits.MISSION_START)
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
        attack_surface=mission.attack_surface.get_summary() if mission.attack_surface else None,
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
    target: str | None = Query(None, max_length=200, description="Filter by target (partial match)"),
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
            current_phase=get_mission_summary_dict(m).get("current_phase"),
            logs=m.logs or [],
            directive=m.directive,
            findings=get_mission_output_findings(m),
        )
        for m in missions
    ]
    return PaginatedResponse(items=items, total=total, page=page, per_page=per_page)


@router.get("/{mission_id}/findings", response_model=list[MissionFindingSummary])
async def get_mission_findings(
    mission_id: str,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
) -> list[MissionFindingSummary]:
    """Get all findings for a specific mission."""
    repo = MissionRepository(db)
    mission = await repo.get_by_id(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    check_resource_owner(mission, _current_user, "mission")
    raw_findings = get_mission_output_findings(mission)
    return [
        MissionFindingSummary(
            id=str(i),
            title=f.get("title", "Untitled"),
            severity=f.get("severity", "info"),
            status=f.get("status", "potential"),
            description=f.get("description", ""),
            tool_source=f.get("tool_source", f.get("tool", "")),
            created_at=f.get("created_at", ""),
        )
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
            attack_surface=mission.attack_surface.get_summary() if mission.attack_surface else None,
        )

    # Try DB
    repo = MissionRepository(db)
    db_mission = await repo.get_by_id(mission_id)

    if not db_mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    check_resource_owner(db_mission, _current_user, "mission")
    summary = get_mission_summary_dict(db_mission)

    return MissionResponse(
        id=db_mission.id,
        target=db_mission.target,
        status=db_mission.status,
        current_phase=summary.get("current_phase"),
        logs=db_mission.logs or [],
        directive=db_mission.directive,
        findings=get_mission_output_findings(db_mission),
    )


@router.delete(
    "/{mission_id}",
    response_model=MissionDeleteResponse,
    summary="Delete mission",
    description="Permanently delete a completed or failed mission and its associated storage data.",
)
async def delete_mission(
    mission_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = require_permission(Permission.MANAGE_MISSIONS),
) -> MissionDeleteResponse:
    """Delete a mission and clean up associated filesystem data."""
    repo = MissionRepository(db)
    mission = await repo.get_by_id(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    check_resource_owner(mission, _current_user, "mission")

    active_statuses = {
        "created",
        "initializing",
        "scoping",
        "planning",
        "running",
        "scanning",
        "analyzing",
        "executing",
        "exploiting",
        "paused",
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

    return MissionDeleteResponse(status="deleted", mission_id=mission_id)


@router.post(
    "/{mission_id}/stop",
    response_model=StatusResponse,
    summary="Stop mission",
    description="Stop a running mission. The mission must be in an active state.",
)
@limiter.limit(RateLimits.MISSION_CONTROL)
async def stop_mission(
    request: Request,
    response: Response,
    mission_id: str,
    _current_user: User = require_permission(Permission.MANAGE_MISSIONS),
    session: AsyncSession = Depends(get_async_session),
) -> StatusResponse:
    """Stop a running mission. Requires superuser privileges."""
    active = await mission_manager.get_mission(mission_id)
    if active:
        check_resource_owner(active, _current_user, "mission")
    result = await mission_manager.stop_mission(mission_id)
    if not result:
        raise HTTPException(status_code=404, detail="Mission not found or not active")

    await audit_log_event(
        session,
        AuditEventType.MISSION_STATUS_CHANGED,
        user_id=str(_current_user.id),
        details={"mission_id": str(mission_id), "action": "stopped"},
        request=request,
    )

    return StatusResponse(message="Mission stopping")


@router.post(
    "/{mission_id}/pause",
    response_model=StatusResponse,
    summary="Pause mission",
    description="Pause a running mission. It can be resumed later.",
)
@limiter.limit(RateLimits.MISSION_CONTROL)
async def pause_mission(
    request: Request,
    response: Response,
    mission_id: str,
    _current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> StatusResponse:
    """Pause a running mission."""
    active = await mission_manager.get_mission(mission_id)
    if active:
        check_resource_owner(active, _current_user, "mission")
    result = await mission_manager.pause_mission(mission_id)
    if not result:
        raise HTTPException(status_code=404, detail="Mission not found or not active")

    await audit_log_event(
        session,
        AuditEventType.MISSION_STATUS_CHANGED,
        user_id=str(_current_user.id),
        details={"mission_id": str(mission_id), "action": "paused"},
        request=request,
    )

    return StatusResponse(message="Mission paused")


@router.post(
    "/{mission_id}/resume",
    response_model=StatusResponse,
    summary="Resume mission",
    description="Resume a previously paused mission from where it left off.",
)
@limiter.limit(RateLimits.MISSION_CONTROL)
async def resume_mission(
    request: Request,
    response: Response,
    mission_id: str,
    _current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> StatusResponse:
    """Resume a paused mission."""
    active = await mission_manager.get_mission(mission_id)
    if active:
        check_resource_owner(active, _current_user, "mission")
    result = await mission_manager.resume_mission(mission_id)
    if not result:
        raise HTTPException(status_code=404, detail="Mission not found or not active")

    await audit_log_event(
        session,
        AuditEventType.MISSION_STATUS_CHANGED,
        user_id=str(_current_user.id),
        details={"mission_id": str(mission_id), "action": "resumed"},
        request=request,
    )

    return StatusResponse(message="Mission resumed")
