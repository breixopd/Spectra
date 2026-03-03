"""
Mission API Router.

Endpoints for managing security missions.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_active_user
from app.api.schemas import MissionResponse, StartMissionRequest
from app.core.database import get_async_session
from app.core.rate_limit import limiter
from app.models.user import User
import logging
from app.repositories.mission import MissionRepository
from app.services.mission import mission_manager

logger = logging.getLogger("spectra.api.missions")

# Pagination limits
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20

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
async def get_scan_presets():
    """Get available scan presets."""
    from app.services.mission.presets import SCAN_PRESETS
    return SCAN_PRESETS


@router.get("/adversary-playbooks")
async def get_adversary_playbooks():
    """List available adversary simulation playbooks."""
    from app.services.ai.adversary_playbooks import list_adversary_playbooks

    return list_adversary_playbooks()


@router.get("/adversary-playbooks/{playbook_id}")
async def get_adversary_playbook_detail(playbook_id: str):
    """Get full details of an adversary playbook."""
    from app.services.ai.adversary_playbooks import get_adversary_playbook

    pb = get_adversary_playbook(playbook_id)
    if not pb:
        raise HTTPException(status_code=404, detail="Playbook not found")
    return pb.model_dump()


@router.get("/exploit-chains")
async def get_exploit_chains():
    """List available exploit chains."""
    from app.services.mission.chain_builder import get_builtin_chains

    return [c.model_dump() for c in get_builtin_chains()]


@router.get("/attack-summary")
async def get_attack_coverage(
    _current_user: User = Depends(get_current_active_user),
):
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


@router.post("", response_model=MissionResponse)
@limiter.limit("5/minute")
async def start_mission(
    request: Request,
    response: Response,
    mission_request: StartMissionRequest,
    _current_user: User = Depends(get_current_active_user),
):
    """Start a new mission.

    Rate limited to 5 missions per minute per user.
    """
    mission_id = await mission_manager.start_mission(
        mission_request.target, mission_request.directive
    )
    mission = await mission_manager.get_mission(mission_id)

    if not mission:
        raise HTTPException(status_code=500, detail="Failed to create mission")

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


@router.get("", response_model=List[MissionResponse])
async def list_missions(
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="Max records to return",
    ),
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
):
    """List all missions (active and historical).

    Pagination: max 100 items per page.
    """
    repo = MissionRepository(db)
    missions = await repo.get_all(skip=skip, limit=min(limit, MAX_PAGE_SIZE))

    return [
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


@router.get("/{mission_id}/report/pdf")
async def download_pdf_report(
    mission_id: str,
    session: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
):
    """Download mission report as PDF."""
    from fastapi.responses import Response as FastAPIResponse

    from app.services.mission.report_generator import generate_pdf_report

    repo = MissionRepository(session)
    mission = await repo.get_by_id(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")

    mission_data = {
        "id": mission.id,
        "target": mission.target,
        "status": mission.status,
        "findings": mission.summary.get("findings", []) if mission.summary else [],
        "logs": mission.logs or [],
        "tools_run": mission.summary.get("tools_run", []) if mission.summary else [],
        "attack_surface": mission.attack_surface or {},
    }

    pdf_bytes = generate_pdf_report(mission_data)
    if not pdf_bytes:
        raise HTTPException(status_code=500, detail="PDF generation failed")

    return FastAPIResponse(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=spectra_report_{mission_id[:8]}.pdf"
        },
    )


@router.get("/{mission_id}", response_model=MissionResponse)
async def get_mission(
    mission_id: str,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
):
    """Get mission status."""
    # Try active missions first
    mission = await mission_manager.get_mission(mission_id)

    if mission:
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


@router.post("/{mission_id}/stop")
@limiter.limit("10/minute")
async def stop_mission(
    request: Request,
    response: Response,
    mission_id: str,
    _current_user: User = Depends(get_current_active_user),
):
    """Stop a running mission."""
    await mission_manager.stop_mission(mission_id)
    return {"message": "Mission stopping"}


@router.post("/{mission_id}/pause")
@limiter.limit("10/minute")
async def pause_mission(
    request: Request,
    response: Response,
    mission_id: str,
    _current_user: User = Depends(get_current_active_user),
):
    """Pause a running mission."""
    await mission_manager.pause_mission(mission_id)
    return {"message": "Mission paused"}


@router.post("/{mission_id}/resume")
@limiter.limit("10/minute")
async def resume_mission(
    request: Request,
    response: Response,
    mission_id: str,
    _current_user: User = Depends(get_current_active_user),
):
    """Resume a paused mission."""
    await mission_manager.resume_mission(mission_id)
    return {"message": "Mission resumed"}


@router.get("/{mission_id}/diff/{other_mission_id}")
async def diff_missions(
    mission_id: str,
    other_mission_id: str,
    db: AsyncSession = Depends(get_async_session),
    _current_user: User = Depends(get_current_active_user),
):
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

    new_db = await repo.get_by_id(other_mission_id)
    if not new_db:
        raise HTTPException(
            status_code=404, detail=f"Mission {other_mission_id} not found"
        )

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
):
    """
    Steer a running mission.

    Allows human-in-the-loop control:
    - skip_phase: Skip a specific phase (e.g., enumeration)
    - prioritize_target: Focus on a specific target/service
    - focus_vuln: Prioritize a specific vulnerability
    """

    try:
        result = await mission_manager.steer_mission(
            mission_id=mission_id,
            action=steer_request.action,
            phase=steer_request.phase,
            target=steer_request.target,
            vulnerability=steer_request.vulnerability,
        )
        return result
    except ValueError as e:
        logger.error(f"Mission steering error: {e}")
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail="Mission or target not found")
        raise HTTPException(status_code=400, detail="Invalid steering request")
