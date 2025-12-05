"""
Mission API Router.

Endpoints for managing security missions.
"""

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_active_user
from app.api.schemas import MissionResponse, StartMissionRequest
from app.core.database import get_async_session
from app.core.rate_limit import limiter
from app.models.user import User
from app.repositories.mission import MissionRepository
from app.services.mission import mission_manager

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
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
