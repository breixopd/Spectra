"""Garage (S3-compatible) tiered storage implementation.

Uses two separate buckets for HOT and COLD tiers.  Objects are moved
between buckets on promotion/demotion, and access tracking is kept in
Redis (falling back to in-memory state when no Redis client is provided).
"""

import logging
import time
from typing import Any

from .interface import StorageObject, StorageTier, TieredStorage
from .metrics import MetricsCollector
from .policy import PromotionConfig, TTLCalculator, determine_tier

logger = logging.getLogger(__name__)


class _InMemoryTracker:
    """In-memory access tracker used when no Redis client is available."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        return self._data.get(key)

    async def set(self, key: str, fields: dict[str, Any]) -> None:
        self._data[key] = fields

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)


class GarageTieredStorage(TieredStorage):
    """Garage-compatible tiered storage using separate hot/cold buckets.

    Access tracking uses Redis when available; otherwise falls back to an
    in-memory dictionary (suitable for single-process testing).

    Promotion copies an object from the COLD bucket to the HOT bucket and
    removes the COLD copy.  Demotion does the reverse.
    """

    def __init__(
        self,
        hot_bucket: str,
        cold_bucket: str,
        s3_client: Any,
        redis_client: Any = None,
        promo_config: PromotionConfig | None = None,
        ttl_calc: TTLCalculator | None = None,
        metrics: MetricsCollector | None = None,
    ) -> None:
        """Initialize GarageTieredStorage.

        Args:
            hot_bucket: Name of the Garage bucket for HOT-tier objects.
            cold_bucket: Name of the Garage bucket for COLD-tier objects.
            s3_client: An aioboto3 S3 client (async).
            redis_client: Optional async Redis client for access tracking.
            promo_config: Optional promotion thresholds.
            ttl_calc: Optional TTL calculator.
            metrics: Optional metrics collector.
        """
        self._hot_bucket = hot_bucket
        self._cold_bucket = cold_bucket
        self._s3 = s3_client
        self._redis = redis_client
        self._tracker = redis_client if redis_client else _InMemoryTracker()
        self._promo = promo_config or PromotionConfig()
        self._ttl = ttl_calc or TTLCalculator()
        self._metrics = metrics or MetricsCollector()

    # ---- helpers -------------------------------------------------------

    async def _head(self, bucket: str, key: str) -> dict[str, Any] | None:
        """Return object metadata from S3 HEAD, or None if missing."""
        try:
            resp = await self._s3.head_object(Bucket=bucket, Key=key)
            return resp
        except Exception:
            return None

    async def _read_access_meta(self, key: str) -> dict[str, Any]:
        """Read access-tracking fields for a key."""
        raw = await self._tracker.get(key)
        return raw or {}

    async def _write_access_meta(self, key: str, fields: dict[str, Any]) -> None:
        await self._tracker.set(key, fields)

    async def _record_access(self, key: str) -> None:
        meta = await self._read_access_meta(key)
        meta["access_count"] = meta.get("access_count", 0) + 1
        meta["last_accessed"] = time.time()
        await self._write_access_meta(key, meta)

    async def _delete_access_meta(self, key: str) -> None:
        await self._tracker.delete(key)

    # ---- TieredStorage interface ---------------------------------------

    async def put(
        self,
        key: str,
        data: bytes,
        metadata: dict | None = None,
        tier: StorageTier = StorageTier.HOT,
    ) -> None:
        bucket = self._hot_bucket if tier == StorageTier.HOT else self._cold_bucket
        extra = metadata or {}
        try:
            await self._s3.put_object(Bucket=bucket, Key=key, Body=data, Metadata=extra)
        except Exception as exc:
            logger.error("put(%s) failed: %s", key, exc)
            raise RuntimeError(f"Failed to store object {key}") from exc

        # Initialize access metadata
        await self._write_access_meta(
            key,
            {
                "access_count": 0,
                "last_accessed": time.time(),
                "tier": tier.value,
            },
        )

    async def get(self, key: str) -> bytes | None:
        # Try HOT bucket first
        resp = await self._head(self._hot_bucket, key)
        bucket = self._hot_bucket
        if resp is None:
            resp = await self._head(self._cold_bucket, key)
            bucket = self._cold_bucket

        if resp is None:
            return None

        try:
            result = await self._s3.get_object(Bucket=bucket, Key=key)
            body = await result["Body"].read()
        except Exception as exc:
            logger.error("get(%s) failed: %s", key, exc)
            return None

        await self._record_access(key)

        # Check if promotion is warranted
        meta = await self._read_access_meta(key)
        current_tier = StorageTier(meta.get("tier", StorageTier.HOT.value))
        new_tier = determine_tier(
            key,
            meta.get("access_count", 0),
            meta.get("last_accessed", 0.0),
            current_tier,
            self._promo,
            self._ttl,
        )
        if new_tier == StorageTier.HOT and current_tier == StorageTier.COLD:
            await self.promote(key)

        return body

    async def touch(self, key: str) -> None:
        await self._record_access(key)

    async def promote(self, key: str) -> None:
        """Copy object from COLD to HOT bucket and delete the COLD copy."""
        try:
            resp = await self._s3.get_object(Bucket=self._cold_bucket, Key=key)
            body = await resp["Body"].read()
            await self._s3.put_object(Bucket=self._hot_bucket, Key=key, Body=body)
            await self._s3.delete_object(Bucket=self._cold_bucket, Key=key)
        except Exception as exc:
            logger.error("promote(%s) failed: %s", key, exc)
            return

        await self._write_access_meta(key, {"tier": StorageTier.HOT.value})
        self._metrics.record_promotion(key)
        logger.info("Promoted %s to HOT", key)

    async def demote(self, key: str) -> None:
        """Copy object from HOT to COLD bucket and delete the HOT copy."""
        try:
            resp = await self._s3.get_object(Bucket=self._hot_bucket, Key=key)
            body = await resp["Body"].read()
            await self._s3.put_object(Bucket=self._cold_bucket, Key=key, Body=body)
            await self._s3.delete_object(Bucket=self._hot_bucket, Key=key)
        except Exception as exc:
            logger.error("demote(%s) failed: %s", key, exc)
            return

        await self._write_access_meta(key, {"tier": StorageTier.COLD.value})
        self._metrics.record_demotion(key)
        logger.info("Demoted %s to COLD", key)

    async def get_tier_info(self, key: str) -> StorageObject | None:
        head = await self._head(self._hot_bucket, key)
        tier = StorageTier.HOT
        size = 0
        if head is None:
            head = await self._head(self._cold_bucket, key)
            tier = StorageTier.COLD
        if head is None:
            return None

        size = head.get("ContentLength", 0)
        meta = await self._read_access_meta(key)
        return StorageObject(
            key=key,
            tier=tier,
            size_bytes=size,
            last_accessed=meta.get("last_accessed", 0.0),
            access_count=meta.get("access_count", 0),
        )

    async def delete(self, key: str) -> None:
        for bucket in (self._hot_bucket, self._cold_bucket):
            try:
                await self._s3.delete_object(Bucket=bucket, Key=key)
            except Exception:
                pass

        await self._delete_access_meta(key)
        self._metrics.record_deletion(key)
