"""
Lightweight Redis client wrapper for optional Redis-backed caching.

Provides a thin async interface over redis-py with connection pooling,
graceful degradation when Redis is unavailable, and JSON serialization.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from redis.asyncio import Redis
from redis.asyncio.connection import ConnectionPool

from spectra_platform.core.config import settings

logger = logging.getLogger(__name__)


class RedisConnectionPool:
    """Singleton connection pool for Redis."""

    _instance: ConnectionPool | None = None

    @classmethod
    def get_pool(cls) -> ConnectionPool | None:
        """Return the shared connection pool, creating it on first call."""
        if cls._instance is None:
            redis_url = settings.REDIS_URL or settings.RATE_LIMIT_STORAGE
            if not redis_url.startswith(("redis://", "rediss://")):
                logger.warning("Redis URL not configured (%s); Redis cache disabled", redis_url)
                return None
            try:
                cls._instance = ConnectionPool.from_url(redis_url)
            except Exception as exc:
                logger.warning("Failed to create Redis connection pool: %s", exc)
                return None
        return cls._instance

    @classmethod
    async def close_pool(cls) -> None:
        """Close the shared pool and reset the singleton."""
        if cls._instance is not None:
            await cls._instance.aclose()
            cls._instance = None


class RedisCache:
    """Async Redis cache with JSON serialization and graceful fallback."""

    def __init__(self) -> None:
        pool = RedisConnectionPool.get_pool()
        self._client: Redis | None = Redis(connection_pool=pool) if pool else None

    async def get(self, key: str) -> Any | None:
        """Fetch and deserialize a cached value."""
        if not self._client:
            return None
        try:
            raw = await self._client.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            logger.warning("Redis get error for %s: %s", key, exc)
            return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Serialize and store a value with an optional TTL in seconds."""
        if not self._client:
            return False
        try:
            payload = json.dumps(value, default=str)
            if ttl is not None and ttl > 0:
                await self._client.setex(key, ttl, payload)
            else:
                await self._client.set(key, payload)
            return True
        except Exception as exc:
            logger.warning("Redis set error for %s: %s", key, exc)
            return False

    async def delete(self, key: str) -> bool:
        """Remove a key from the cache."""
        if not self._client:
            return False
        try:
            result = await self._client.delete(key)
            return result > 0
        except Exception as exc:
            logger.warning("Redis delete error for %s: %s", key, exc)
            return False

    async def set_nx(self, key: str, *, ttl_seconds: int, value: str = "1") -> bool:
        """Set ``key`` to ``value`` with expiry only if absent.

        Returns True if this caller acquired the key (should process).
        Returns False if the key was already present (duplicate / in-flight).
        When Redis is unavailable, returns True so callers degrade to previous behaviour.
        """
        if not self._client:
            return True
        if ttl_seconds <= 0:
            ttl_seconds = 60
        try:
            inserted = await self._client.set(name=key, value=value, ex=ttl_seconds, nx=True)
            return inserted is True
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Redis set_nx error for %s: %s", key, exc)
            return True

    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching a glob-style pattern."""
        if not self._client:
            return 0
        try:
            keys: list[str] = []
            async for key in self._client.scan_iter(match=pattern):
                keys.append(key)
            if keys:
                await self._client.delete(*keys)
            return len(keys)
        except Exception as exc:
            logger.warning("Redis delete_pattern error for %s: %s", pattern, exc)
            return 0


__all__ = [
    "RedisCache",
    "RedisConnectionPool",
]
