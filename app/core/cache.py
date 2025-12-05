"""
Redis Caching Layer for Spectra.

Provides a centralized caching service with:
- TTL-based expiration
- JSON serialization for complex objects
- Cache invalidation patterns
- Statistics and monitoring
"""

import hashlib
import json
import logging
from functools import wraps
from typing import Any, Callable, ParamSpec, TypeVar

try:
    import orjson
except ImportError:
    orjson = None  # type: ignore

from redis.asyncio import Redis

logger = logging.getLogger("spectra.core.cache")

P = ParamSpec("P")
T = TypeVar("T")


def _json_dumps(obj: Any) -> bytes:
    """Serialize object to JSON bytes."""
    if orjson:
        return orjson.dumps(obj)
    return json.dumps(obj).encode("utf-8")


def _json_loads(data: bytes | str) -> Any:
    """Deserialize JSON bytes/str to object."""
    if orjson:
        return orjson.loads(data)
    return json.loads(data)


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
    Redis-based caching service.

    Usage:
        cache = CacheService(redis_client)

        # Simple get/set
        await cache.set("key", {"data": "value"}, ttl=300)
        data = await cache.get("key")

        # With decorator
        @cache.cached(ttl=300, prefix="tool")
        async def get_tool(tool_id: str):
            ...
    """

    def __init__(self, redis: Redis):
        self.redis = redis
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
            Cached value or None if not found
        """
        try:
            data = await self.redis.get(key)
            if data:
                self._stats["hits"] += 1
                return orjson.loads(data)
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
        Set a value in cache.

        Args:
            key: Cache key
            value: Value to cache (must be JSON serializable)
            ttl: Time to live in seconds

        Returns:
            True if successful
        """
        try:
            data = orjson.dumps(value, default=str)
            await self.redis.setex(key, ttl, data)
            self._stats["sets"] += 1
            return True
        except Exception as e:
            logger.warning("Cache set error for %s: %s", key, e)
            return False

    async def delete(self, key: str) -> bool:
        """Delete a key from cache."""
        try:
            result = await self.redis.delete(key)
            self._stats["deletes"] += 1
            return result > 0
        except Exception as e:
            logger.warning("Cache delete error for %s: %s", key, e)
            return False

    async def delete_pattern(self, pattern: str) -> int:
        """
        Delete all keys matching a pattern.

        Args:
            pattern: Redis glob pattern (e.g., "cache:tool:*")

        Returns:
            Number of keys deleted
        """
        try:
            keys = []
            async for key in self.redis.scan_iter(match=pattern):
                keys.append(key)

            if keys:
                deleted = await self.redis.delete(*keys)
                self._stats["deletes"] += deleted
                return deleted
            return 0
        except Exception as e:
            logger.warning("Cache delete pattern error for %s: %s", pattern, e)
            return 0

    async def exists(self, key: str) -> bool:
        """Check if a key exists in cache."""
        try:
            return bool(await self.redis.exists(key))
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

    async def get_redis_stats(self) -> dict[str, Any]:
        """Get Redis server statistics."""
        try:
            info = await self.redis.info("memory")
            keyspace = await self.redis.info("keyspace")

            return {
                "used_memory_human": info.get("used_memory_human", "unknown"),
                "used_memory_peak_human": info.get("used_memory_peak_human", "unknown"),
                "total_keys": sum(
                    db.get("keys", 0)
                    for db in keyspace.values()
                    if isinstance(db, dict)
                ),
            }
        except Exception as e:
            logger.warning("Failed to get Redis stats: %s", e)
            return {"error": str(e)}


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
