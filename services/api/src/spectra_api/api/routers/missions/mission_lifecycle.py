"""Mission lifecycle: delete, stop, pause, resume (paths under /{mission_id})."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_api.api.dependencies import check_resource_owner, validate_uuid_param
from spectra_api.api.schemas.common import StatusResponse
from spectra_api.api.schemas.mission import MissionDeleteResponse
from spectra_api.authz import Permission, require_permission
from spectra_auth.rate_limit import RateLimits, limiter
from spectra_mission.manager import mission_manager
from spectra_persistence.database import get_async_session
from spectra_persistence.models.audit_log import AuditEventType
from spectra_persistence.models.user import User
from spectra_persistence.repositories.mission import MissionRepository
from spectra_system.audit import log_event as audit_log_event

router = APIRouter()


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
    validate_uuid_param(mission_id, "mission_id")
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

    from spectra_common.config import settings
    from spectra_storage_policy.storage import get_storage_service

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
    """Stop a running mission."""
    validate_uuid_param(mission_id, "mission_id")
    repo = MissionRepository(session)
    mission = await repo.get_by_id(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    check_resource_owner(mission, _current_user, "mission")
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
    _current_user: User = require_permission(Permission.MANAGE_MISSIONS),
    session: AsyncSession = Depends(get_async_session),
) -> StatusResponse:
    """Pause a running mission."""
    validate_uuid_param(mission_id, "mission_id")
    repo = MissionRepository(session)
    mission = await repo.get_by_id(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    check_resource_owner(mission, _current_user, "mission")
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
    _current_user: User = require_permission(Permission.MANAGE_MISSIONS),
    session: AsyncSession = Depends(get_async_session),
) -> StatusResponse:
    """Resume a paused mission."""
    validate_uuid_param(mission_id, "mission_id")
    repo = MissionRepository(session)
    mission = await repo.get_by_id(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    check_resource_owner(mission, _current_user, "mission")
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
