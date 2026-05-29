"""AWS S3 native tiered storage using lifecycle policies.

Instead of separate buckets, this implementation uses a single S3 bucket
and maps HOT → STANDARD and COLD → GLACIER storage classes via S3 lifecycle
rules.  Promotion transitions an object back to STANDARD.
"""

import logging
import time
from typing import Any

from .interface import StorageObject, StorageTier, TieredStorage
from .metrics import MetricsCollector

logger = logging.getLogger(__name__)

# Map our logical tiers to S3 storage classes.
_TIER_TO_CLASS: dict[StorageTier, str] = {
    StorageTier.HOT: "STANDARD",
    StorageTier.COLD: "GLACIER",
}

# Map back from S3 storage class to logical tier.
_CLASS_TO_TIER: dict[str, StorageTier] = {
    "STANDARD": StorageTier.HOT,
    "STANDARD_IA": StorageTier.COLD,
    "GLACIER": StorageTier.COLD,
    "GLACIER_IR": StorageTier.COLD,
    "DEEP_ARCHIVE": StorageTier.COLD,
}


class S3TieredStorage(TieredStorage):
    """AWS S3 tiered storage using a single bucket with storage-class controls.

    Objects are stored with S3 storage classes: STANDARD for HOT and
    GLACIER for COLD.  Promotion is a storage-class transition; actual
    lifecycle rules should be configured on the bucket for automated
    cold→glacier move, but this class handles explicit promote/demote
    via copy with storage-class override.
    """

    def __init__(
        self,
        bucket: str,
        s3_client: Any,
        metrics: MetricsCollector | None = None,
    ) -> None:
        """Initialize S3TieredStorage.

        Args:
            bucket: Name of the S3 bucket.
            s3_client: An aioboto3 S3 client (async).
            metrics: Optional metrics collector.
        """
        self._bucket = bucket
        self._s3 = s3_client
        self._metrics = metrics or MetricsCollector()

    # ---- helpers -------------------------------------------------------

    async def _head(self, key: str) -> dict[str, Any] | None:
        try:
            return await self._s3.head_object(Bucket=self._bucket, Key=key)
        except Exception:
            return None

    def _storage_class_to_tier(self, sc: str) -> StorageTier:
        return _CLASS_TO_TIER.get(sc, StorageTier.HOT)

    # ---- TieredStorage interface ---------------------------------------

    async def put(
        self,
        key: str,
        data: bytes,
        metadata: dict | None = None,
        tier: StorageTier = StorageTier.HOT,
    ) -> None:
        extra = metadata or {}
        storage_class = _TIER_TO_CLASS[tier]
        try:
            await self._s3.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                Metadata=extra,
                StorageClass=storage_class,
            )
        except Exception as exc:
            logger.error("put(%s) failed: %s", key, exc)
            raise RuntimeError(f"Failed to store object {key}") from exc

    async def get(self, key: str) -> bytes | None:
        try:
            resp = await self._s3.get_object(Bucket=self._bucket, Key=key)
            body = await resp["Body"].read()
        except Exception as exc:
            logger.warning("get(%s) failed: %s", key, exc)
            return None

        # Promote to STANDARD on every access
        await self._promote_to_standard(key)

        return body

    async def touch(self, key: str) -> None:
        head = await self._head(key)
        if head is None:
            return
        # Use copy with metadata directive REPLACE to update LastModified.
        try:
            await self._s3.copy_object(
                Bucket=self._bucket,
                Key=key,
                CopySource={"Bucket": self._bucket, "Key": key},
                MetadataDirective="REPLACE",
                Metadata=head.get("Metadata", {}),
                StorageClass="STANDARD",
            )
        except Exception as exc:
            logger.warning("touch(%s) failed: %s", key, exc)

    async def promote(self, key: str) -> None:
        await self._promote_to_standard(key)
        self._metrics.record_promotion(key)
        logger.info("Promoted %s to STANDARD", key)

    async def demote(self, key: str) -> None:
        try:
            await self._s3.copy_object(
                Bucket=self._bucket,
                Key=key,
                CopySource={"Bucket": self._bucket, "Key": key},
                MetadataDirective="COPY",
                StorageClass="GLACIER",
            )
        except Exception as exc:
            logger.error("demote(%s) failed: %s", key, exc)
            return

        self._metrics.record_demotion(key)
        logger.info("Demoted %s to GLACIER", key)

    async def get_tier_info(self, key: str) -> StorageObject | None:
        head = await self._head(key)
        if head is None:
            return None

        storage_class = head.get("StorageClass", "STANDARD")
        tier = self._storage_class_to_tier(storage_class)
        size = head.get("ContentLength", 0)
        last_modified = head.get("LastModified")
        last_accessed = last_modified.timestamp() if last_modified else 0.0

        return StorageObject(
            key=key,
            tier=tier,
            size_bytes=size,
            last_accessed=last_accessed,
            access_count=0,
        )

    async def delete(self, key: str) -> None:
        try:
            await self._s3.delete_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            logger.warning("delete(%s) failed: %s", key, exc)
            return

        self._metrics.record_deletion(key)

    # ---- internal ------------------------------------------------------

    async def _promote_to_standard(self, key: str) -> None:
        """Copy the object onto itself with STANDARD storage class."""
        try:
            await self._s3.copy_object(
                Bucket=self._bucket,
                Key=key,
                CopySource={"Bucket": self._bucket, "Key": key},
                MetadataDirective="COPY",
                StorageClass="STANDARD",
            )
        except Exception as exc:
            logger.warning("_promote_to_standard(%s) failed: %s", key, exc)
