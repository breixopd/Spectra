from datetime import UTC, datetime

import pytest

from app.services.mission import artifact_workspace as workspace_module
from app.services.mission.artifact_workspace import MissionArtifactWorkspace


class _FakeStorage:
    def __init__(self):
        self.objects = {}

    async def upload(self, bucket, key, data):
        self.objects[(bucket, key)] = data
        return f"s3://{bucket}/{key}"

    async def download(self, bucket, key):
        item = self.objects.get((bucket, key))
        if item is None:
            raise FileNotFoundError(key)
        return item

    async def delete(self, bucket, key):
        return self.objects.pop((bucket, key), None) is not None

    async def get_presigned_url(self, bucket, key, expires=3600):
        if (bucket, key) not in self.objects:
            return None
        return f"https://storage.local/{bucket}/{key}?expires={expires}"


@pytest.fixture
def fake_storage(monkeypatch):
    storage = _FakeStorage()
    monkeypatch.setattr(workspace_module, "get_storage_service", lambda: storage)
    monkeypatch.setattr(workspace_module.settings, "S3_BUCKET_MISSIONS", "missions")
    return storage


@pytest.mark.asyncio
async def test_workspace_upload_list_download_and_delete(fake_storage):
    workspace = MissionArtifactWorkspace("mission-1")

    artifact = await workspace.put_artifact(
        filename="../payload.sh",
        content=b"echo scoped",
        kind="payload",
        labels=["file-drop"],
    )

    assert artifact.filename == "payload.sh"
    assert artifact.kind == "payload"
    assert len(artifact.sha256) == 64
    assert await workspace.list_artifacts(kind="payload") == [artifact]

    url = await workspace.presigned_download_url(artifact, expires=120)
    assert url and "payload.sh" in url

    assert await workspace.delete_artifact(artifact.id)
    assert await workspace.list_artifacts() == []


@pytest.mark.asyncio
async def test_file_drop_token_expires(fake_storage, monkeypatch):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(workspace_module, "_now", lambda: now)
    workspace = MissionArtifactWorkspace("mission-1")
    artifact = await workspace.put_artifact(filename="tool.sh", content=b"#!/bin/sh", kind="payload")
    token = await workspace.create_download_token(artifact.id, ttl_seconds=60)

    assert (await workspace.resolve_download_token(token.token)).id == artifact.id

    monkeypatch.setattr(workspace_module, "_now", lambda: datetime(2026, 1, 1, 0, 2, tzinfo=UTC))
    assert await workspace.resolve_download_token(token.token) is None
