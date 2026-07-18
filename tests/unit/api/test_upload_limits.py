"""Resource-limit regression tests for multipart upload endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, status


@pytest.mark.asyncio
async def test_mission_artifact_rejects_oversized_content_before_storage():
    from spectra_api.api.routers.missions import artifacts

    upload = MagicMock(filename="large.bin")
    upload.read = AsyncMock(return_value=b"12345")

    with (
        patch.object(artifacts, "MAX_ARTIFACT_SIZE", 4),
        patch.object(artifacts, "_ensure_mission_owner", new=AsyncMock()),
        patch.object(artifacts, "MissionArtifactWorkspace") as workspace_cls,
        pytest.raises(HTTPException) as exc_info,
    ):
        await artifacts.upload_mission_artifact(
            request=MagicMock(),
            mission_id="mission-1",
            file=upload,
            kind="artifact",
            session=MagicMock(),
            current_user=MagicMock(),
        )

    assert exc_info.value.status_code == status.HTTP_413_CONTENT_TOO_LARGE
    upload.read.assert_awaited_once_with(5)
    workspace_cls.assert_not_called()


@pytest.mark.asyncio
async def test_pentest_evidence_rejects_oversized_content_before_storage():
    from spectra_api.api.routers import pentest_sessions

    upload = MagicMock(filename="evidence.txt", content_type="text/plain")
    upload.read = AsyncMock(return_value=b"12345")

    with (
        patch.object(pentest_sessions, "MAX_EVIDENCE_SIZE", 4),
        patch.object(pentest_sessions, "_load_owned_session", new=AsyncMock(return_value={"id": "session-1"})),
        patch.object(pentest_sessions, "get_storage_service") as storage_factory,
        pytest.raises(HTTPException) as exc_info,
    ):
        await pentest_sessions.upload_evidence.__wrapped__(
            request=MagicMock(),
            session_id="session-1",
            file=upload,
            _current_user=MagicMock(),
        )

    assert exc_info.value.status_code == status.HTTP_413_CONTENT_TOO_LARGE
    upload.read.assert_awaited_once_with(5)
    storage_factory.assert_not_called()
