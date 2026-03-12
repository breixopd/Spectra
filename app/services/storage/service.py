"""S3-compatible storage service with local filesystem fallback."""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.config import settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger("spectra.storage")

_storage_service: StorageService | None = None


def _import_s3_deps() -> tuple[Any, Any, Any]:
    """Lazy-import S3 dependencies. Only called when S3 is enabled."""
    import aioboto3 as _aioboto3
    from botocore.config import Config as _BotoConfig
    from botocore.exceptions import ClientError as _ClientError

    return _aioboto3, _BotoConfig, _ClientError


class StorageService:
    """Unified storage interface for S3/MinIO and local filesystem.

    When S3_ENDPOINT_URL is configured, uses S3. Otherwise falls back to local disk.
    All paths use forward slashes and are relative within buckets.
    """

    def __init__(self) -> None:
        self._s3_enabled = bool(settings.S3_ENDPOINT_URL)
        self._session: Any = None
        self._buckets_ensured: set[str] = set()
        self._client_error: type[Exception] = Exception
        if self._s3_enabled:
            _aioboto3, self._boto_config_cls, self._client_error = _import_s3_deps()
            self._session = _aioboto3.Session()
            logger.info("Storage: S3 mode (endpoint=%s)", settings.S3_ENDPOINT_URL)
        else:
            logger.info("Storage: local filesystem mode")

    @property
    def is_s3(self) -> bool:
        return self._s3_enabled

    def _s3_kwargs(self) -> dict:
        """Build kwargs for S3 client creation."""
        return {
            "service_name": "s3",
            "endpoint_url": settings.S3_ENDPOINT_URL,
            "aws_access_key_id": settings.S3_ACCESS_KEY.get_secret_value(),
            "aws_secret_access_key": settings.S3_SECRET_KEY.get_secret_value(),
            "region_name": settings.S3_REGION,
            "config": self._boto_config_cls(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "adaptive"},
            ),
        }

    async def _ensure_bucket(self, bucket: str) -> None:
        """Create bucket if it doesn't exist (idempotent)."""
        if not self._s3_enabled or bucket in self._buckets_ensured:
            return
        try:
            async with self._session.client(**self._s3_kwargs()) as s3:
                try:
                    await s3.head_bucket(Bucket=bucket)
                except self._client_error:
                    await s3.create_bucket(Bucket=bucket)
                    logger.info("Created S3 bucket: %s", bucket)
            self._buckets_ensured.add(bucket)
        except Exception:
            logger.exception("Failed to ensure bucket %s", bucket)

    def _local_path(self, bucket: str, key: str) -> Path:
        """Map bucket/key to local filesystem path with traversal protection."""
        bucket_map = {
            settings.S3_BUCKET_MISSIONS: Path("data/missions"),
            settings.S3_BUCKET_SESSIONS: Path("data/sessions"),
            settings.S3_BUCKET_KNOWLEDGE: Path("data/cache"),
            settings.S3_BUCKET_BACKUPS: Path("data/backups"),
        }
        base = bucket_map.get(bucket, Path(f"data/{bucket}"))
        full = base / key
        if not str(full.resolve()).startswith(str(base.resolve())):
            raise ValueError("Path traversal detected")
        return full

    async def upload(self, bucket: str, key: str, data: bytes) -> str:
        """Upload data to storage. Returns the full path/URI."""
        if self._s3_enabled:
            await self._ensure_bucket(bucket)
            async with self._session.client(**self._s3_kwargs()) as s3:
                await s3.put_object(Bucket=bucket, Key=key, Body=data)
            logger.debug("S3 upload: %s/%s (%d bytes)", bucket, key, len(data))
            return f"s3://{bucket}/{key}"
        else:
            path = self._local_path(bucket, key)
            path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(path.write_bytes, data)
            logger.debug("Local upload: %s (%d bytes)", path, len(data))
            return str(path)

    async def upload_file(self, bucket: str, key: str, file_path: str | Path) -> str:
        """Upload a local file to storage."""
        file_path = Path(file_path)
        if self._s3_enabled:
            await self._ensure_bucket(bucket)
            async with self._session.client(**self._s3_kwargs()) as s3:
                await s3.upload_file(str(file_path), bucket, key)
            logger.debug("S3 upload_file: %s → %s/%s", file_path, bucket, key)
            return f"s3://{bucket}/{key}"
        else:
            dest = self._local_path(bucket, key)
            dest.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(shutil.copy2, str(file_path), str(dest))
            logger.debug("Local copy: %s → %s", file_path, dest)
            return str(dest)

    async def download(self, bucket: str, key: str) -> bytes:
        """Download data from storage."""
        if self._s3_enabled:
            async with self._session.client(**self._s3_kwargs()) as s3:
                response = await s3.get_object(Bucket=bucket, Key=key)
                data = await response["Body"].read()
            logger.debug("S3 download: %s/%s (%d bytes)", bucket, key, len(data))
            return data
        else:
            path = self._local_path(bucket, key)
            data = await asyncio.to_thread(path.read_bytes)
            logger.debug("Local read: %s (%d bytes)", path, len(data))
            return data

    async def download_file(self, bucket: str, key: str, dest_path: str | Path) -> Path:
        """Download a file from storage to local path."""
        dest_path = Path(dest_path)
        if self._s3_enabled:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            async with self._session.client(**self._s3_kwargs()) as s3:
                await s3.download_file(bucket, key, str(dest_path))
            logger.debug("S3 download_file: %s/%s → %s", bucket, key, dest_path)
        else:
            src = self._local_path(bucket, key)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(shutil.copy2, str(src), str(dest_path))
            logger.debug("Local copy: %s → %s", src, dest_path)
        return dest_path

    async def delete(self, bucket: str, key: str) -> bool:
        """Delete an object from storage."""
        try:
            if self._s3_enabled:
                async with self._session.client(**self._s3_kwargs()) as s3:
                    await s3.delete_object(Bucket=bucket, Key=key)
                logger.debug("S3 delete: %s/%s", bucket, key)
            else:
                path = self._local_path(bucket, key)
                if path.is_file():
                    await asyncio.to_thread(path.unlink)
                elif path.is_dir():
                    await asyncio.to_thread(shutil.rmtree, str(path))
                logger.debug("Local delete: %s", path)
            return True
        except Exception:
            logger.exception("Delete failed: %s/%s", bucket, key)
            return False

    async def exists(self, bucket: str, key: str) -> bool:
        """Check if an object exists."""
        try:
            if self._s3_enabled:
                async with self._session.client(**self._s3_kwargs()) as s3:
                    await s3.head_object(Bucket=bucket, Key=key)
                return True
            else:
                return self._local_path(bucket, key).exists()
        except self._client_error:
            return False
        except Exception:
            return False

    async def list_objects(self, bucket: str, prefix: str = "") -> list[str]:
        """List object keys in a bucket with optional prefix."""
        if self._s3_enabled:
            keys = []
            async with self._session.client(**self._s3_kwargs()) as s3:
                paginator = s3.get_paginator("list_objects_v2")
                async for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                    for obj in page.get("Contents", []):
                        keys.append(obj["Key"])
            return keys
        else:
            base = self._local_path(bucket, prefix) if prefix else self._local_path(bucket, "")
            if not base.exists():
                return []
            files = []
            for p in base.rglob("*"):
                if p.is_file():
                    rel = p.relative_to(self._local_path(bucket, ""))
                    files.append(str(rel))
            return files

    async def get_presigned_url(self, bucket: str, key: str, expires: int = 3600) -> str | None:
        """Generate a presigned download URL (S3 only)."""
        if not self._s3_enabled:
            return None
        try:
            async with self._session.client(**self._s3_kwargs()) as s3:
                url = await s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": bucket, "Key": key},
                    ExpiresIn=expires,
                )
            return url
        except Exception:
            logger.exception("Presigned URL failed: %s/%s", bucket, key)
            return None

    async def copy(self, src_bucket: str, src_key: str, dst_bucket: str, dst_key: str) -> bool:
        """Copy an object between buckets."""
        try:
            if self._s3_enabled:
                await self._ensure_bucket(dst_bucket)
                async with self._session.client(**self._s3_kwargs()) as s3:
                    await s3.copy_object(
                        CopySource={"Bucket": src_bucket, "Key": src_key},
                        Bucket=dst_bucket,
                        Key=dst_key,
                    )
            else:
                src = self._local_path(src_bucket, src_key)
                dst = self._local_path(dst_bucket, dst_key)
                dst.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(shutil.copy2, str(src), str(dst))
            return True
        except Exception:
            logger.exception("Copy failed: %s/%s → %s/%s", src_bucket, src_key, dst_bucket, dst_key)
            return False

    async def migrate_bucket(self, src_bucket: str, dst_bucket: str) -> int:
        """Migrate all objects from one bucket to another. Returns count of migrated objects."""
        keys = await self.list_objects(src_bucket)
        count = 0
        for key in keys:
            if await self.copy(src_bucket, key, dst_bucket, key):
                count += 1
        logger.info("Migrated %d/%d objects: %s → %s", count, len(keys), src_bucket, dst_bucket)
        return count

    async def health_check(self) -> dict:
        """Check storage health."""
        if not self._s3_enabled:
            return {"status": "healthy", "mode": "local", "path": "data/"}
        try:
            async with self._session.client(**self._s3_kwargs()) as s3:
                await s3.list_buckets()
            return {"status": "healthy", "mode": "s3", "endpoint": settings.S3_ENDPOINT_URL}
        except Exception as e:
            return {"status": "unhealthy", "mode": "s3", "error": str(e)}

    async def close(self) -> None:
        """Clean up resources."""
        self._session = None
        logger.debug("Storage service closed")


def get_storage_service() -> StorageService:
    """Get or create the singleton storage service."""
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageService()
    return _storage_service


async def close_storage_service() -> None:
    """Close the storage service."""
    global _storage_service
    if _storage_service is not None:
        await _storage_service.close()
        _storage_service = None
