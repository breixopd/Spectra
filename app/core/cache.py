"""
PostgreSQL Caching Layer for Spectra.

Provides a centralized caching service with:
- TTL-based expiration
- JSON serialization for complex objects
- Cache invalidation patterns
- Statistics and monitoring

NOTE: Periodic cleanup of expired entries should be handled externally
(e.g., a scheduled task running DELETE FROM cache_entries WHERE expires_at < now()).
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Callable, ParamSpec, TypeVar

try:
    import orjson
except ImportError:
    orjson = None  # type: ignore

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import async_session_maker
from app.models.infrastructure import CacheEntry

logger = logging.getLogger("spectra.core.cache")

P = ParamSpec("P")
T = TypeVar("T")


def _json_dumps(obj: Any) -> str:
    """Serialize object to JSON string."""
    if orjson:
        return orjson.dumps(obj, default=str).decode("utf-8")
    return json.dumps(obj, default=str)


def _json_loads(data: str | bytes) -> Any:
    """Deserialize JSON string to object."""
    if orjson:
        return orjson.loads(data)
    return json.loads(data)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CacheConfig:
    """Cache configuration constants."""

    # TTL defaults (in seconds)
    TTL_SHORT = 60  # 1 minute
    TTL_MEDIUM = 300  # 5 minutes
    TTL_LONG = 3600  # 1 hour
    TTL_DAY = 86400  # 24 hours

    # Key prefixes
    PREFIX_TOOL = "cache:tool:"
    PREFIX_MISSION = "cache:mission:"
    PREFIX_FINDING = "cache:finding:"
    PREFIX_RAG = "cache:rag:"
    PREFIX_STATS = "cache:stats:"


class CacheService:
    """
    PostgreSQL-based caching service.

    Usage:
        cache = CacheService()

        # Simple get/set
        await cache.set("key", {"data": "value"}, ttl=300)
        data = await cache.get("key")

        # With decorator
        @cache.cached(ttl=300, prefix="tool")
        async def get_tool(tool_id: str):
            ...
    """

    def __init__(self, session_maker: async_sessionmaker[AsyncSession] | None = None):
        self._session_maker = session_maker or async_session_maker
        self._stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "deletes": 0,
        }

    async def get(self, key: str) -> Any | None:
        """
        Get a value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        try:
            async with self._session_maker() as session:
                now = _now()
                stmt = select(CacheEntry.value).where(
                    CacheEntry.key == key,
                    (CacheEntry.expires_at.is_(None)) | (CacheEntry.expires_at > now),
                )
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                if row is not None:
                    self._stats["hits"] += 1
                    return _json_loads(row)
                self._stats["misses"] += 1
                return None
        except Exception as e:
            logger.warning("Cache get error for %s: %s", key, e)
            self._stats["misses"] += 1
            return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int = CacheConfig.TTL_MEDIUM,
    ) -> bool:
        """
        Set a value in cache using upsert.

        Args:
            key: Cache key
            value: Value to cache (must be JSON serializable)
            ttl: Time to live in seconds

        Returns:
            True if successful
        """
        try:
            now = _now()
            expires_at = now + timedelta(seconds=ttl)
            json_value = _json_dumps(value)

            async with self._session_maker() as session:
                # Use dialect-aware upsert: PostgreSQL ON CONFLICT, SQLite fallback
                dialect = session.bind.dialect.name if session.bind else "postgresql"
                if dialect == "postgresql":
                    stmt = pg_insert(CacheEntry).values(
                        key=key,
                        value=json_value,
                        expires_at=expires_at,
                        created_at=now,
                    ).on_conflict_do_update(
                        index_elements=["key"],
                        set_={
                            "value": json_value,
                            "expires_at": expires_at,
                            "created_at": now,
                        },
                    )
                    await session.execute(stmt)
                else:
                    existing = await session.get(CacheEntry, key)
                    if existing:
                        existing.value = json_value
                        existing.expires_at = expires_at
                        existing.created_at = now
                    else:
                        session.add(CacheEntry(
                            key=key,
                            value=json_value,
                            expires_at=expires_at,
                            created_at=now,
                        ))
                await session.commit()
            self._stats["sets"] += 1
            return True
        except Exception as e:
            logger.warning("Cache set error for %s: %s", key, e)
            return False

    async def delete(self, key: str) -> bool:
        """Delete a key from cache."""
        try:
            async with self._session_maker() as session:
                stmt = delete(CacheEntry).where(CacheEntry.key == key)
                result = await session.execute(stmt)
                await session.commit()
                deleted = result.rowcount > 0
                if deleted:
                    self._stats["deletes"] += 1
                return deleted
        except Exception as e:
            logger.warning("Cache delete error for %s: %s", key, e)
            return False

    async def delete_pattern(self, pattern: str) -> int:
        """
        Delete all keys matching a pattern.

        Args:
            pattern: Glob-style pattern (e.g., "cache:tool:*")
                     Converted to SQL LIKE: * -> %

        Returns:
            Number of keys deleted
        """
        try:
            sql_pattern = pattern.replace("*", "%")
            async with self._session_maker() as session:
                stmt = delete(CacheEntry).where(CacheEntry.key.like(sql_pattern))
                result = await session.execute(stmt)
                await session.commit()
                count = result.rowcount
                self._stats["deletes"] += count
                return count
        except Exception as e:
            logger.warning("Cache delete pattern error for %s: %s", pattern, e)
            return 0

    async def get_by_pattern(self, pattern: str) -> list[Any]:
        """
        Get all non-expired values matching a key pattern.

        Args:
            pattern: Glob-style pattern (e.g., "spectra:system:operations:*")
                     Converted to SQL LIKE: * -> %

        Returns:
            List of deserialized values
        """
        try:
            sql_pattern = pattern.replace("*", "%")
            async with self._session_maker() as session:
                now = _now()
                stmt = select(CacheEntry.value).where(
                    CacheEntry.key.like(sql_pattern),
                    (CacheEntry.expires_at.is_(None)) | (CacheEntry.expires_at > now),
                )
                result = await session.execute(stmt)
                rows = result.scalars().all()
                return [_json_loads(row) for row in rows]
        except Exception as e:
            logger.warning("Cache get_by_pattern error for %s: %s", pattern, e)
            return []

    async def exists(self, key: str) -> bool:
        """Check if a key exists in cache (and is not expired)."""
        try:
            async with self._session_maker() as session:
                now = _now()
                stmt = select(func.count()).select_from(CacheEntry).where(
                    CacheEntry.key == key,
                    (CacheEntry.expires_at.is_(None)) | (CacheEntry.expires_at > now),
                )
                result = await session.execute(stmt)
                return result.scalar_one() > 0
        except Exception as e:
            logger.warning("Cache exists error for %s: %s", key, e)
            return False

    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Any],
        ttl: int = CacheConfig.TTL_MEDIUM,
    ) -> Any:
        """
        Get from cache or compute and store.

        Args:
            key: Cache key
            factory: Async function to compute value if not cached
            ttl: Time to live in seconds

        Returns:
            Cached or computed value
        """
        value = await self.get(key)
        if value is not None:
            return value

        # Compute value
        if callable(factory):
            import asyncio

            if asyncio.iscoroutinefunction(factory):
                value = await factory()
            else:
                value = factory()
        else:
            value = factory

        await self.set(key, value, ttl)
        return value

    def cached(
        self,
        ttl: int = CacheConfig.TTL_MEDIUM,
        prefix: str = "fn",
        key_builder: Callable[..., str] | None = None,
    ):
        """
        Decorator for caching function results.

        Args:
            ttl: Time to live in seconds
            prefix: Cache key prefix
            key_builder: Optional custom key builder function

        Example:
            @cache.cached(ttl=300, prefix="tool")
            async def get_tool(tool_id: str):
                ...
        """

        def decorator(func: Callable[P, T]) -> Callable[P, T]:
            @wraps(func)
            async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                # Build cache key
                if key_builder:
                    cache_key = key_builder(*args, **kwargs)
                else:
                    # Default key: prefix:function_name:hash(args)
                    key_parts = [prefix, func.__name__]
                    arg_str = json.dumps(
                        {"args": args, "kwargs": kwargs},
                        sort_keys=True,
                        default=str,
                    )
                    key_hash = hashlib.sha256(arg_str.encode()).hexdigest()[:16]
                    cache_key = ":".join(key_parts + [key_hash])

                # Try cache
                cached_value = await self.get(cache_key)
                if cached_value is not None:
                    return cached_value  # type: ignore

                # Execute function
                result = await func(*args, **kwargs)  # type: ignore

                # Cache result
                await self.set(cache_key, result, ttl)

                return result

            return wrapper  # type: ignore

        return decorator

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = (self._stats["hits"] / total * 100) if total > 0 else 0.0

        return {
            **self._stats,
            "total_requests": total,
            "hit_rate_percent": round(hit_rate, 2),
        }


# --- Tool-Specific Cache Functions ---


async def get_cached_tool(
    cache: CacheService,
    tool_id: str,
    factory: Callable,
) -> Any:
    """Get tool from cache or load it."""
    key = f"{CacheConfig.PREFIX_TOOL}{tool_id}"
    return await cache.get_or_set(key, factory, CacheConfig.TTL_LONG)


async def invalidate_tool_cache(cache: CacheService, tool_id: str | None = None) -> int:
    """Invalidate tool cache (single tool or all)."""
    if tool_id:
        await cache.delete(f"{CacheConfig.PREFIX_TOOL}{tool_id}")
        return 1
    return await cache.delete_pattern(f"{CacheConfig.PREFIX_TOOL}*")


# Global cache instance (initialized in lifespan)
_cache: CacheService | None = None


def get_cache() -> CacheService | None:
    """Get global cache instance."""
    return _cache


def set_cache(cache: CacheService) -> None:
    """Set global cache instance."""
    global _cache
    _cache = cache


__all__ = [
    "CacheConfig",
    "CacheService",
    "get_cache",
    "set_cache",
    "get_cached_tool",
    "invalidate_tool_cache",
]