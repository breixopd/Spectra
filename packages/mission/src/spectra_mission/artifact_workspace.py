"""Mission-scoped artifact workspace backed by object storage."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from spectra_common.config import settings
from spectra_common.errors import StorageError
from spectra_storage_policy.storage import get_storage_service

_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")
_MANIFEST_NAME = "manifest.json"
_MAX_TOKEN_TTL_SECONDS = 3600


@dataclass
class MissionArtifact:
    id: str
    filename: str
    kind: str
    key: str
    size: int
    sha256: str
    created_at: str
    expires_at: str | None = None
    labels: list[str] | None = None


@dataclass
class ArtifactDownloadToken:
    token: str
    artifact_id: str
    key: str
    expires_at: str


def _workspace_prefix(mission_id: str) -> str:
    return f"{mission_id}/workspace"


def _manifest_key(mission_id: str) -> str:
    return f"{_workspace_prefix(mission_id)}/{_MANIFEST_NAME}"


def _sanitize_filename(filename: str) -> str:
    safe = _SAFE_NAME_RE.sub("_", filename.strip()).strip("._")
    return safe[:180] or "artifact.bin"


def _now() -> datetime:
    return datetime.now(UTC)


class MissionArtifactWorkspace:
    """Small productized workspace for mission artifacts and file drops."""

    def __init__(self, mission_id: str) -> None:
        self.mission_id = mission_id
        self.bucket = settings.S3_BUCKET_MISSIONS
        self.storage = get_storage_service()

    async def _load_manifest(self) -> dict:
        try:
            raw = await self.storage.download(self.bucket, _manifest_key(self.mission_id))
            data = json.loads(raw.decode())
            if isinstance(data, dict):
                data.setdefault("artifacts", [])
                data.setdefault("tokens", [])
                return data
        except (FileNotFoundError, json.JSONDecodeError, StorageError, RuntimeError, OSError, ValueError):
            pass
        return {"artifacts": [], "tokens": []}

    async def _save_manifest(self, manifest: dict) -> None:
        await self.storage.upload(
            self.bucket,
            _manifest_key(self.mission_id),
            json.dumps(manifest, indent=2, sort_keys=True).encode(),
        )

    async def list_artifacts(self, kind: str | None = None) -> list[MissionArtifact]:
        manifest = await self._load_manifest()
        artifacts = [MissionArtifact(**item) for item in manifest.get("artifacts", []) if isinstance(item, dict)]
        if kind:
            artifacts = [artifact for artifact in artifacts if artifact.kind == kind]
        return artifacts

    async def put_artifact(
        self,
        *,
        filename: str,
        content: bytes,
        kind: str = "artifact",
        labels: list[str] | None = None,
        ttl_seconds: int | None = None,
    ) -> MissionArtifact:
        artifact_id = secrets.token_urlsafe(12)
        safe_name = _sanitize_filename(filename)
        key = f"{_workspace_prefix(self.mission_id)}/artifacts/{artifact_id}/{safe_name}"
        digest = hashlib.sha256(content).hexdigest()
        now = _now()
        expires_at = None
        if ttl_seconds:
            expires_at = (now + timedelta(seconds=max(60, min(ttl_seconds, 30 * 86400)))).isoformat()

        artifact = MissionArtifact(
            id=artifact_id,
            filename=safe_name,
            kind=kind,
            key=key,
            size=len(content),
            sha256=digest,
            created_at=now.isoformat(),
            expires_at=expires_at,
            labels=labels or [],
        )
        manifest = await self._load_manifest()
        manifest["artifacts"] = [item for item in manifest.get("artifacts", []) if item.get("id") != artifact_id]
        manifest["artifacts"].append(asdict(artifact))
        await self.storage.upload(self.bucket, key, content)
        await self._save_manifest(manifest)
        return artifact

    async def get_artifact(self, artifact_id: str) -> MissionArtifact | None:
        for artifact in await self.list_artifacts():
            if artifact.id == artifact_id:
                return artifact
        return None

    async def delete_artifact(self, artifact_id: str) -> bool:
        manifest = await self._load_manifest()
        artifacts = manifest.get("artifacts", [])
        artifact = next((item for item in artifacts if item.get("id") == artifact_id), None)
        if not artifact:
            return False
        await self.storage.delete(self.bucket, artifact["key"])
        manifest["artifacts"] = [item for item in artifacts if item.get("id") != artifact_id]
        await self._save_manifest(manifest)
        return True

    async def create_download_token(self, artifact_id: str, ttl_seconds: int = 900) -> ArtifactDownloadToken:
        artifact = await self.get_artifact(artifact_id)
        if artifact is None:
            raise FileNotFoundError("Artifact not found")
        ttl = max(60, min(ttl_seconds, _MAX_TOKEN_TTL_SECONDS))
        token = ArtifactDownloadToken(
            token=secrets.token_urlsafe(24),
            artifact_id=artifact_id,
            key=artifact.key,
            expires_at=(_now() + timedelta(seconds=ttl)).isoformat(),
        )
        manifest = await self._load_manifest()
        active_tokens = []
        for item in manifest.get("tokens", []):
            try:
                if datetime.fromisoformat(item["expires_at"]) > _now():
                    active_tokens.append(item)
            except (KeyError, ValueError, TypeError):
                continue
        active_tokens.append(asdict(token))
        manifest["tokens"] = active_tokens
        await self._save_manifest(manifest)
        return token

    async def resolve_download_token(self, token_value: str) -> MissionArtifact | None:
        manifest = await self._load_manifest()
        token = next((item for item in manifest.get("tokens", []) if item.get("token") == token_value), None)
        if not token:
            return None
        try:
            if datetime.fromisoformat(token["expires_at"]) <= _now():
                return None
        except (KeyError, ValueError, TypeError):
            return None
        return await self.get_artifact(token["artifact_id"])

    async def presigned_download_url(self, artifact: MissionArtifact, expires: int = 900) -> str | None:
        return await self.storage.get_presigned_url(self.bucket, artifact.key, expires=max(60, min(expires, 3600)))
