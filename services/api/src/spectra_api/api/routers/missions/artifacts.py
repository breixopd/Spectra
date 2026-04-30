"""Mission artifact workspace API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.models.audit_log import AuditEventType
from app.models.user import User
from app.repositories.mission import MissionRepository
from app.services.mission.artifact_workspace import MissionArtifact, MissionArtifactWorkspace
from app.services.system.audit import log_event as audit_log_event
from spectra_api.api.dependencies import check_resource_owner, get_current_active_user, validate_uuid_param

router = APIRouter()


class ArtifactResponse(BaseModel):
    id: str
    filename: str
    kind: str
    key: str
    size: int
    sha256: str
    created_at: str
    expires_at: str | None = None
    labels: list[str] = []


class ArtifactDownloadResponse(BaseModel):
    artifact_id: str
    url: str
    expires_in: int


class FileDropResponse(BaseModel):
    artifact_id: str
    token: str
    url_path: str
    expires_at: str


async def _ensure_mission_owner(mission_id: str, session: AsyncSession, user: User) -> None:
    validate_uuid_param(mission_id, "mission_id")
    repo = MissionRepository(session)
    mission = await repo.get_by_id(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    check_resource_owner(mission, user, "mission")


def _artifact_response(artifact: MissionArtifact) -> ArtifactResponse:
    return ArtifactResponse(
        id=artifact.id,
        filename=artifact.filename,
        kind=artifact.kind,
        key=artifact.key,
        size=artifact.size,
        sha256=artifact.sha256,
        created_at=artifact.created_at,
        expires_at=artifact.expires_at,
        labels=artifact.labels or [],
    )


@router.get("/{mission_id}/artifacts", response_model=list[ArtifactResponse])
async def list_mission_artifacts(
    mission_id: str,
    kind: str | None = Query(None),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_active_user),
) -> list[ArtifactResponse]:
    await _ensure_mission_owner(mission_id, session, current_user)
    workspace = MissionArtifactWorkspace(mission_id)
    return [_artifact_response(artifact) for artifact in await workspace.list_artifacts(kind=kind)]


@router.post("/{mission_id}/artifacts", response_model=ArtifactResponse)
async def upload_mission_artifact(
    request: Request,
    mission_id: str,
    file: Annotated[UploadFile, File()],
    kind: str = Query("artifact", pattern=r"^[a-zA-Z0-9_-]{1,40}$"),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_active_user),
) -> ArtifactResponse:
    await _ensure_mission_owner(mission_id, session, current_user)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Artifact file is empty")
    workspace = MissionArtifactWorkspace(mission_id)
    artifact = await workspace.put_artifact(filename=file.filename or "artifact.bin", content=content, kind=kind)
    await audit_log_event(
        session,
        AuditEventType.MISSION_ARTIFACT_CREATED,
        user_id=str(current_user.id),
        details={"mission_id": mission_id, "artifact_id": artifact.id, "kind": kind, "sha256": artifact.sha256},
        request=request,
    )
    return _artifact_response(artifact)


@router.post("/{mission_id}/artifacts/{artifact_id}/download", response_model=ArtifactDownloadResponse)
async def create_artifact_download_url(
    mission_id: str,
    artifact_id: str,
    expires: int = Query(900, ge=60, le=3600),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_active_user),
) -> ArtifactDownloadResponse:
    await _ensure_mission_owner(mission_id, session, current_user)
    workspace = MissionArtifactWorkspace(mission_id)
    artifact = await workspace.get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    url = await workspace.presigned_download_url(artifact, expires=expires)
    if not url:
        raise HTTPException(status_code=503, detail="Artifact download URL unavailable")
    return ArtifactDownloadResponse(artifact_id=artifact_id, url=url, expires_in=expires)


@router.post("/{mission_id}/artifacts/{artifact_id}/file-drop", response_model=FileDropResponse)
async def create_file_drop_token(
    request: Request,
    mission_id: str,
    artifact_id: str,
    ttl_seconds: int = Query(900, ge=60, le=3600),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_active_user),
) -> FileDropResponse:
    await _ensure_mission_owner(mission_id, session, current_user)
    workspace = MissionArtifactWorkspace(mission_id)
    token = await workspace.create_download_token(artifact_id, ttl_seconds=ttl_seconds)
    await audit_log_event(
        session,
        AuditEventType.MISSION_FILE_DROP_CREATED,
        user_id=str(current_user.id),
        details={"mission_id": mission_id, "artifact_id": artifact_id, "expires_at": token.expires_at},
        request=request,
    )
    return FileDropResponse(
        artifact_id=artifact_id,
        token=token.token,
        url_path=f"/api/v1/missions/{mission_id}/artifacts/file-drop/{token.token}",
        expires_at=token.expires_at,
    )


@router.get("/{mission_id}/artifacts/file-drop/{token}")
async def resolve_file_drop(
    mission_id: str,
    token: str,
) -> dict[str, str]:
    validate_uuid_param(mission_id, "mission_id")
    workspace = MissionArtifactWorkspace(mission_id)
    artifact = await workspace.resolve_download_token(token)
    if artifact is None:
        raise HTTPException(status_code=404, detail="File drop not found or expired")
    url = await workspace.presigned_download_url(artifact, expires=300)
    if not url:
        raise HTTPException(status_code=503, detail="File drop unavailable")
    return {"url": url, "filename": artifact.filename, "sha256": artifact.sha256}


@router.delete("/{mission_id}/artifacts/{artifact_id}", status_code=204)
async def delete_mission_artifact(
    request: Request,
    mission_id: str,
    artifact_id: str,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_active_user),
) -> None:
    await _ensure_mission_owner(mission_id, session, current_user)
    workspace = MissionArtifactWorkspace(mission_id)
    deleted = await workspace.delete_artifact(artifact_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Artifact not found")
    await audit_log_event(
        session,
        AuditEventType.MISSION_ARTIFACT_DELETED,
        user_id=str(current_user.id),
        details={"mission_id": mission_id, "artifact_id": artifact_id},
        request=request,
    )
