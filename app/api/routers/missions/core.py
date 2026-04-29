"""Mission core endpoints — start/list, per-mission CRUD and lifecycle (catalog lives in mission_catalog)."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from spectra_common.constants import API_DEFAULT_PAGE_SIZE as DEFAULT_PAGE_SIZE
from spectra_common.constants import API_MAX_PAGE_SIZE as MAX_PAGE_SIZE
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    check_feature_allowed,
    check_mission_limit,
    check_resource_owner,
    check_storage_limit,
    get_current_active_user,
    validate_uuid_param,
    verify_api_quota_for_user,
)
from app.api.schemas import (
    MissionFindingSummary,
    MissionResponse,
    PaginatedResponse,
    StartMissionRequest,
)
from app.auth.rate_limit import RateLimits, limiter
from app.auth.rbac import Permission, require_permission
from app.core.database import get_async_session
from app.models.audit_log import AuditEventType
from app.models.user import User
from app.models.user_preferences import UserPreferences
from app.repositories.mission import MissionRepository
from app.services.compliance.mission_abuse import evaluate_mission_abuse
from app.services.mission.manager import mission_manager
from app.services.mission.output_model import (
    get_mission_findings as get_mission_output_findings,
)
from app.services.mission.output_model import (
    get_mission_summary_dict,
)
from app.services.system.audit import log_event as audit_log_event

logger = logging.getLogger(__name__)

router = APIRouter()


async def _resolved_launch_prefs(
    session: AsyncSession,
    user_id: str,
    body: StartMissionRequest,
) -> tuple[bool, str]:
    """Merge API body with stored user defaults for approval and scan mode."""
    result = await session.execute(select(UserPreferences).where(UserPreferences.user_id == user_id))
    prefs = result.scalar_one_or_none()
    pref_approval = bool(prefs.prefer_mission_approval) if prefs else False
    scan = (prefs.default_scan_mode if prefs else None) or "autonomous"
    if scan not in ("autonomous", "guided", "manual"):
        scan = "autonomous"

    effective_approval = body.requires_approval if body.requires_approval is not None else pref_approval
    effective_scan = body.scan_mode or scan
    return effective_approval, effective_scan


@router.post(
    "",
    response_model=MissionResponse,
    status_code=status.HTTP_201_CREATED,
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
    await verify_api_quota_for_user(_current_user)

    eff_requires, eff_scan = await _resolved_launch_prefs(db, str(_current_user.id), mission_request)

    if not mission_request.authorization_confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must confirm that you own the target or have explicit written authorization to test it.",
        )

    abuse_decision = evaluate_mission_abuse(
        target=mission_request.target,
        directive=mission_request.directive,
        requirements=mission_request.requirements,
        authorization_confirmed=mission_request.authorization_confirmed,
        requires_approval=eff_requires,
    )
    if not abuse_decision.allowed:
        await audit_log_event(
            db,
            AuditEventType.MISSION_LAUNCH_BLOCKED,
            user_id=str(_current_user.id),
            details={
                "target": mission_request.target,
                "risk_score": abuse_decision.risk_score,
                "reasons": abuse_decision.reasons,
            },
            request=request,
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Mission requires admin review before launch")

    await check_mission_limit(_current_user, db)
    await check_storage_limit(_current_user, db)
    await check_feature_allowed(_current_user, db, "autonomous_mode")

    mission_id = await mission_manager.start_mission(
        mission_request.target,
        mission_request.directive,
        requirements=mission_request.requirements,
        vpn_config=mission_request.vpn_config,
        user_id=str(_current_user.id),
        requires_approval=eff_requires,
        record_demo=mission_request.record_demo,
        playbook_id=mission_request.playbook_id,
        scan_mode=eff_scan,
    )
    mission = await mission_manager.get_mission(mission_id)

    if not mission:
        raise HTTPException(status_code=500, detail="Failed to create mission")

    # Audit log
    await audit_log_event(
        db,
        AuditEventType.MISSION_LAUNCHED,
        user_id=str(_current_user.id),
        details={
            "mission_id": mission_id,
            "target": mission_request.target,
            "authorization_confirmed": mission_request.authorization_confirmed,
            "abuse_risk_score": abuse_decision.risk_score,
            "requires_review": abuse_decision.requires_review,
        },
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
    validate_uuid_param(mission_id, "mission_id")
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
    validate_uuid_param(mission_id, "mission_id")
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
