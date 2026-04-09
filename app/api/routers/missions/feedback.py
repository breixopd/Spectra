"""Mission feedback, approval, steering, progress, and task-tree endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import check_resource_owner, get_current_active_user, validate_uuid_param
from app.api.schemas import ActionApprovalResponse
from app.core.database import get_async_session
from app.core.rate_limit import RateLimits, limiter
from app.models.user import User
from app.repositories.mission import MissionRepository
from app.services.mission.manager import mission_manager
from app.services.mission.types import MissionProgress

logger = logging.getLogger(__name__)

router = APIRouter()


class SteerMissionRequest(BaseModel):
    """Schema for steering a mission."""

    action: str = Field(..., description="Steering action: skip_phase, prioritize_target, focus_vuln")
    phase: str | None = Field(None, description="Phase to skip (for skip_phase action)")
    target: str | None = Field(None, description="Target to prioritize")
    vulnerability: str | None = Field(None, description="Vulnerability to focus on")


class ApproveActionRequest(BaseModel):
    """Schema for approving/rejecting a pending mission action."""

    action_id: str = Field(..., description="ID of the action to approve or reject")
    approved: bool = Field(default=True, description="Whether to approve the action")


class MissionFeedback(BaseModel):
    """User feedback for a completed mission."""

    rating: int = Field(..., ge=1, le=5, description="1-5 star rating")
    comment: str | None = Field(None, max_length=1000, description="Optional feedback comment")


@router.post("/{mission_id}/steer")
@limiter.limit(RateLimits.MISSION_STEER)
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
    validate_uuid_param(mission_id, "mission_id")

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
    validate_uuid_param(mission_id, "mission_id")
    mission = await mission_manager.get_mission(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    check_resource_owner(mission, _current_user, "mission")
    return mission.task_tree.to_dict()


@router.get("/{mission_id}/progress")
async def get_mission_progress(
    mission_id: str,
    _current_user: User = Depends(get_current_active_user),
) -> MissionProgress:
    """Get estimated mission progress."""
    validate_uuid_param(mission_id, "mission_id")
    mission = await mission_manager.get_mission(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    check_resource_owner(mission, _current_user, "mission")
    return mission.get_progress()


@router.post("/{mission_id}/approve", response_model=ActionApprovalResponse)
async def approve_action(
    mission_id: str,
    body: ApproveActionRequest,
    _current_user: User = Depends(get_current_active_user),
) -> ActionApprovalResponse:
    """Approve or reject a pending action in a mission that requires approval."""
    validate_uuid_param(mission_id, "mission_id")
    mission = await mission_manager.get_mission(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    check_resource_owner(mission, _current_user, "mission")

    if not getattr(mission, "requires_approval", False):
        raise HTTPException(status_code=400, detail="Mission does not require approval")

    from app.core.websocket import manager

    await manager.broadcast_to_room_json(
        f"mission:{mission_id}",
        {
            "type": "action_approval",
            "action_id": body.action_id,
            "approved": body.approved,
        },
    )
    return ActionApprovalResponse(status="approval_sent", action_id=body.action_id, approved=body.approved)


@router.post("/{mission_id}/feedback")
async def submit_mission_feedback(
    mission_id: str,
    feedback: MissionFeedback,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_active_user),
):
    """Submit feedback for a completed mission. Helps improve AI performance via TensorZero."""
    validate_uuid_param(mission_id, "mission_id")
    repo = MissionRepository(db)
    mission = await repo.get_by_id(mission_id)
    if not mission:
        raise HTTPException(404, "Mission not found")

    check_resource_owner(mission, current_user, "mission")

    if mission.status not in ("completed", "exploitation_successful", "failed"):
        raise HTTPException(400, "Feedback can only be submitted for finished missions")

    mission.feedback_rating = feedback.rating
    mission.feedback_comment = feedback.comment
    await db.commit()

    try:
        score = (feedback.rating - 1) / 4.0
        logger.info("Mission %s feedback: %d stars (score=%.2f)", mission_id, feedback.rating, score)
    except Exception:
        logger.debug("TZ feedback send skipped (no inference tracking yet)")

    return {"status": "ok", "message": "Thank you for your feedback!"}


@router.get("/{mission_id}/feedback")
async def get_mission_feedback(
    mission_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_active_user),
):
    """Get feedback for a mission."""
    validate_uuid_param(mission_id, "mission_id")
    repo = MissionRepository(db)
    mission = await repo.get_by_id(mission_id)
    if not mission:
        raise HTTPException(404, "Mission not found")
    check_resource_owner(mission, current_user, "mission")
    return {
        "rating": mission.feedback_rating,
        "comment": mission.feedback_comment,
        "has_feedback": mission.feedback_rating is not None,
    }
