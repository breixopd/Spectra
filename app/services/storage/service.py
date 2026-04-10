"""S3-compatible object storage service (Garage, AWS S3, or any S3-compatible provider)."""

from __future__ import annotations

import logging
from typing import Any

import app.core.config as config

logger = logging.getLogger(__name__)

_storage_service: StorageService | None = None


def _settings():
    return config.settings


def _import_s3_deps() -> tuple[Any, Any, Any]:
    """Lazy-import S3 dependencies."""
    import aioboto3 as _aioboto3
    from botocore.config import Config as _BotoConfig
    from botocore.exceptions import ClientError as _ClientError

    return _aioboto3, _BotoConfig, _ClientError


class _NullContext:
    """Wraps an already-open client so callers can use async-with syntax."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def __aenter__(self) -> Any:
        return self._client

    async def __aexit__(self, *args: Any) -> None:
        pass


class StorageService:
    """S3-compatible object storage (Garage, AWS S3, or any S3-compatible provider).

    Requires S3_ENDPOINT_URL, S3_ACCESS_KEY, and S3_SECRET_KEY to be configured.
    Raises RuntimeError at instantiation if S3 is not configured.
    All paths use forward slashes and are relative within buckets.
    """

    def __init__(self) -> None:
        settings = _settings()
        if not settings.S3_ENDPOINT_URL:
            raise RuntimeError(
                "S3 object storage is required but S3_ENDPOINT_URL is not set. "
                "Configure S3_ENDPOINT_URL, S3_ACCESS_KEY, and S3_SECRET_KEY "
                "(e.g. point to a Garage instance at http://garage:3900) before starting Spectra."
            )
        if not settings.S3_ACCESS_KEY.get_secret_value():
            raise RuntimeError(
                "S3 object storage is configured (S3_ENDPOINT_URL set) "
                "but S3_ACCESS_KEY is missing. Set S3_ACCESS_KEY to continue."
            )
        if not settings.S3_SECRET_KEY.get_secret_value():
            raise RuntimeError(
                "S3 object storage is configured (S3_ENDPOINT_URL set) "
                "but S3_SECRET_KEY is missing. Set S3_SECRET_KEY to continue."
            )

        _aioboto3, self._boto_config_cls, self._client_error = _import_s3_deps()
        self._session = _aioboto3.Session()
        self._buckets_ensured: set[str] = set()
        self._client_ctx: Any = None
        self._s3: Any = None
        logger.info(
            "Storage: S3 mode (endpoint=%s, region=%s, buckets=[%s, %s, %s, %s])",
            settings.S3_ENDPOINT_URL,
            settings.S3_REGION,
            settings.S3_BUCKET_MISSIONS,
            settings.S3_BUCKET_SESSIONS,
            settings.S3_BUCKET_KNOWLEDGE,
            settings.S3_BUCKET_BACKUPS,
        )

    @property
    def is_s3(self) -> bool:
        return True

    def _s3_kwargs(self) -> dict:
        """Build kwargs for S3 client creation."""
        settings = _settings()
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

    async def start(self) -> None:
        """Open a persistent S3 client for the lifetime of this service instance."""
        if self._s3 is not None:
            return
        self._client_ctx = self._session.client(**self._s3_kwargs())
        self._s3 = await self._client_ctx.__aenter__()
        await self._bootstrap_garage()

    # ------------------------------------------------------------------
    # Garage first-boot bootstrap (layout → key → buckets via Admin API)
    # ------------------------------------------------------------------

    async def _bootstrap_garage(self) -> None:
        """Configure Garage on first boot via the Admin API (port 3903).

        Performs layout assignment, key creation, bucket creation, and
        permission grants.  Skips silently when the admin token is empty
        or Garage already has an applied layout.
        """
        settings = _settings()
        admin_token = settings.GARAGE_ADMIN_TOKEN
        if not admin_token:
            return  # no token → skip bootstrap

        admin_url = settings.GARAGE_ADMIN_URL
        if not admin_url:
            # Derive from S3 endpoint: replace port with 3903
            base = settings.S3_ENDPOINT_URL.rsplit(":", 1)[0]
            admin_url = f"{base}:3903"

        import httpx

        headers = {"Authorization": f"Bearer {admin_token}"}

        try:
            async with httpx.AsyncClient(base_url=admin_url, headers=headers, timeout=10) as http:
                # 1. Check current layout status
                resp = await http.get("/v2/status")
                if resp.status_code != 200:
                    logger.debug("Garage admin API not reachable (status %s), skipping bootstrap", resp.status_code)
                    return
                status_data = resp.json()

                # Layout already applied → nothing to do
                layout = status_data.get("layout", {})
                layout_version = layout.get("version")
                if layout_version and layout_version not in (0, "none", None):
                    logger.debug("Garage layout already applied (version %s), skipping bootstrap", layout_version)
                    return

                # 2. Get node ID
                node_resp = await http.get("/v2/node")
                node_resp.raise_for_status()
                node_id = node_resp.json().get("id")
                if not node_id:
                    logger.warning("Garage bootstrap: could not determine node ID")
                    return
                logger.info("Garage bootstrap: node %s — assigning layout", node_id[:16])

                # 3. Assign layout
                assign_resp = await http.post(
                    "/v2/layout",
                    json=[{"id": node_id, "zone": "dc1", "capacity": 1073741824}],
                )
                assign_resp.raise_for_status()

                # 4. Apply layout
                apply_resp = await http.post("/v2/layout/apply", json={"version": 1})
                apply_resp.raise_for_status()
                logger.info("Garage bootstrap: layout applied")

                # 5. Create access key
                key_resp = await http.post("/v2/key", json={"name": "spectra-app"})
                if key_resp.status_code in (200, 201):
                    key_data = key_resp.json()
                    created_access = key_data.get("accessKeyId", "")
                    if created_access:
                        logger.info("Garage bootstrap: created key %s", created_access)
                else:
                    logger.debug("Garage bootstrap: key creation returned %s (may already exist)", key_resp.status_code)
                    created_access = ""

                # Use the configured S3 keys for bucket permissions
                access_key_id = settings.S3_ACCESS_KEY.get_secret_value() or created_access

                # 6. Create buckets and grant permissions
                buckets = [
                    settings.S3_BUCKET_MISSIONS,
                    settings.S3_BUCKET_SESSIONS,
                    settings.S3_BUCKET_KNOWLEDGE,
                    settings.S3_BUCKET_BACKUPS,
                ]
                for bucket_name in buckets:
                    b_resp = await http.put("/v2/bucket", json={"globalAlias": bucket_name})
                    if b_resp.status_code in (200, 201):
                        bucket_id = b_resp.json().get("id", "")
                        logger.info("Garage bootstrap: created bucket %s", bucket_name)
                    elif b_resp.status_code == 409:
                        # Bucket exists — look up its ID
                        list_resp = await http.get("/v2/bucket", params={"alias": bucket_name})
                        bucket_id = list_resp.json().get("id", "") if list_resp.status_code == 200 else ""
                    else:
                        logger.warning("Garage bootstrap: bucket %s creation failed (%s)", bucket_name, b_resp.status_code)
                        continue

                    if bucket_id and access_key_id:
                        await http.post(
                            "/v2/bucket/allow",
                            json={
                                "bucketId": bucket_id,
                                "accessKeyId": access_key_id,
                                "permissions": {"read": True, "write": True, "owner": True},
                            },
                        )

                logger.info("Garage bootstrap complete")

        except Exception:
            logger.warning("Garage bootstrap failed (non-fatal, manual init may be needed)", exc_info=True)

    async def stop(self) -> None:
        """Close the persistent S3 client."""
        if self._client_ctx is not None:
            try:
                await self._client_ctx.__aexit__(None, None, None)
            except Exception:
                logger.debug("Error closing S3 client", exc_info=True)
            self._s3 = None
            self._client_ctx = None

    def _client(self) -> Any:
        """Return a context manager yielding the S3 client."""
        if self._s3 is not None:
            return _NullContext(self._s3)
        return self._session.client(**self._s3_kwargs())

    async def _ensure_bucket(self, bucket: str) -> None:
        """Create bucket if it doesn't exist (idempotent)."""
        if bucket in self._buckets_ensured:
            return
        settings = _settings()
        try:
            async with self._client() as s3:
                try:
                    await s3.head_bucket(Bucket=bucket)
                except self._client_error:
                    await s3.create_bucket(Bucket=bucket)
                    logger.info("Created S3 bucket: %s", bucket)
            self._buckets_ensured.add(bucket)
        except (OSError, ConnectionError) as exc:
            raise RuntimeError(
                f"Cannot reach S3 storage at {settings.S3_ENDPOINT_URL} "
                f'while ensuring bucket "{bucket}". '
                f"Check S3 connectivity and credentials. Error: {exc}"
            ) from exc

    async def upload(self, bucket: str, key: str, data: bytes) -> str:
        """Upload data to S3. Returns the s3:// URI."""
        from botocore.exceptions import BotoCoreError, ClientError

        from app.core.exceptions import StorageError

        await self._ensure_bucket(bucket)
        try:
            async with self._client() as s3:
                await s3.put_object(Bucket=bucket, Key=key, Body=data)
        except (ClientError, BotoCoreError) as exc:
            logger.error("S3 upload failed: bucket=%s key=%s: %s", bucket, key, exc)
            raise StorageError(f"Failed to upload {key}") from exc
        logger.debug("S3 upload: %s/%s (%d bytes)", bucket, key, len(data))
        return f"s3://{bucket}/{key}"

    async def upload_file(self, bucket: str, key: str, file_path: str) -> str:
        """Upload a local file to S3."""
        from botocore.exceptions import BotoCoreError, ClientError

        from app.core.exceptions import StorageError

        await self._ensure_bucket(bucket)
        try:
            async with self._client() as s3:
                await s3.upload_file(str(file_path), bucket, key)
        except (ClientError, BotoCoreError) as exc:
            logger.error("S3 upload_file failed: bucket=%s key=%s: %s", bucket, key, exc)
            raise StorageError(f"Failed to upload file {key}") from exc
        logger.debug("S3 upload_file: %s → %s/%s", file_path, bucket, key)
        return f"s3://{bucket}/{key}"

    async def download(self, bucket: str, key: str) -> bytes:
        """Download data from S3."""
        from botocore.exceptions import BotoCoreError, ClientError

        from app.core.exceptions import StorageError

        try:
            async with self._client() as s3:
                response = await s3.get_object(Bucket=bucket, Key=key)
                data = await response["Body"].read()
        except (ClientError, BotoCoreError) as exc:
            logger.error("S3 download failed: bucket=%s key=%s: %s", bucket, key, exc)
            raise StorageError(f"Failed to download {key}") from exc
        logger.debug("S3 download: %s/%s (%d bytes)", bucket, key, len(data))
        return data

    async def download_file(self, bucket: str, key: str, dest_path: str) -> str:
        """Download an S3 object to a local path."""
        from pathlib import Path

        from botocore.exceptions import BotoCoreError, ClientError

        from app.core.exceptions import StorageError

        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            async with self._client() as s3:
                await s3.download_file(bucket, key, str(dest))
        except (ClientError, BotoCoreError) as exc:
            logger.error("S3 download_file failed: bucket=%s key=%s: %s", bucket, key, exc)
            raise StorageError(f"Failed to download file {key}") from exc
        logger.debug("S3 download_file: %s/%s → %s", bucket, key, dest)
        return str(dest)

    async def delete(self, bucket: str, key: str) -> bool:
        """Delete an object from S3."""
        try:
            async with self._client() as s3:
                await s3.delete_object(Bucket=bucket, Key=key)
            logger.debug("S3 delete: %s/%s", bucket, key)
            return True
        except (OSError, ConnectionError):
            logger.exception("S3 delete failed: %s/%s", bucket, key)
            return False

    async def exists(self, bucket: str, key: str) -> bool:
        """Check if an S3 object exists."""
        try:
            async with self._client() as s3:
                await s3.head_object(Bucket=bucket, Key=key)
            return True
        except self._client_error:
            return False
        except (RuntimeError, ConnectionError, ValueError):
            logger.warning("Unexpected error checking S3 existence: %s/%s", bucket, key, exc_info=True)
            return False

    async def list_objects(self, bucket: str, prefix: str = "") -> list[str]:
        """List object keys in an S3 bucket with optional prefix."""
        keys = []
        async with self._client() as s3:
            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    keys.append(obj["Key"])
        return keys

    async def get_presigned_url(self, bucket: str, key: str, expires: int = 3600) -> str | None:
        """Generate a presigned download URL."""
        try:
            async with self._client() as s3:
                url = await s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": bucket, "Key": key},
                    ExpiresIn=expires,
                )
            return url
        except (OSError, ConnectionError) as exc:
            logger.exception("S3 presigned URL failed: %s/%s: %s", bucket, key, exc)
            return None

    async def copy(self, src_bucket: str, src_key: str, dst_bucket: str, dst_key: str) -> bool:
        """Copy an object between S3 buckets."""
        try:
            await self._ensure_bucket(dst_bucket)
            async with self._client() as s3:
                await s3.copy_object(
                    CopySource={"Bucket": src_bucket, "Key": src_key},
                    Bucket=dst_bucket,
                    Key=dst_key,
                )
            return True
        except (OSError, ConnectionError):
            logger.exception("S3 copy failed: %s/%s → %s/%s", src_bucket, src_key, dst_bucket, dst_key)
            return False

    async def migrate_bucket(self, src_bucket: str, dst_bucket: str) -> int:
        """Migrate all objects from one S3 bucket to another. Returns count of migrated objects."""
        keys = await self.list_objects(src_bucket)
        count = 0
        for key in keys:
            if await self.copy(src_bucket, key, dst_bucket, key):
                count += 1
        logger.info("Migrated %d/%d objects: %s → %s", count, len(keys), src_bucket, dst_bucket)
        return count

    async def health_check(self) -> dict:
        """Check S3 storage health."""
        settings = _settings()
        try:
            async with self._client() as s3:
                # Use head_bucket instead of list_buckets — requires only
                # per-bucket permissions (works with Garage key ACLs).
                bucket = getattr(settings, "S3_BUCKET_MISSIONS", "spectra-missions")
                await s3.head_bucket(Bucket=bucket)
            return {"status": "healthy", "mode": "s3", "endpoint": settings.S3_ENDPOINT_URL}
        except Exception as e:
            logger.warning("Storage health check failed: %s", e)
            return {"status": "unhealthy", "mode": "s3", "endpoint": settings.S3_ENDPOINT_URL, "error": "Storage health check failed"}

    async def close(self) -> None:
        """Clean up resources."""
        self._session = None
        logger.debug("Storage service closed")


def get_storage_service() -> StorageService:
    """Get or create the singleton storage service.

    Raises RuntimeError if S3 is not configured. This is intentional —
    the error should surface at startup so the admin can configure S3.
    """
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageService()
    return _storage_service


async def close_storage_service() -> None:
    """Close the storage service."""
    global _storage_service
    if _storage_service is not None:
        await _storage_service.stop()
        _storage_service = None
