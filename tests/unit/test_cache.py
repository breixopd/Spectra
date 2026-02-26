"""Unit tests for app.core.cache module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import orjson

from app.core.cache import CacheService, CacheConfig, get_cache, set_cache


@pytest.fixture
def mock_redis():
    """Provide a mock async Redis client."""
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.setex = AsyncMock(return_value=True)
    r.delete = AsyncMock(return_value=1)
    r.exists = AsyncMock(return_value=0)
    r.info = AsyncMock(return_value={})
    return r


@pytest.fixture
def cache(mock_redis):
    """Provide a CacheService backed by mock Redis."""
    return CacheService(mock_redis)


class TestCacheServiceGet:
    """Tests for CacheService.get()."""

    @pytest.mark.asyncio
    async def test_get_returns_deserialized_value(self, cache, mock_redis):
        """get() deserializes and returns cached data."""
        payload = {"foo": "bar"}
        mock_redis.get.return_value = orjson.dumps(payload)

        result = await cache.get("key1")

        assert result == payload
        mock_redis.get.assert_awaited_once_with("key1")

    @pytest.mark.asyncio
    async def test_get_miss_returns_none(self, cache, mock_redis):
        """get() returns None and increments misses on cache miss."""
        mock_redis.get.return_value = None

        result = await cache.get("missing")

        assert result is None
        assert cache._stats["misses"] == 1

    @pytest.mark.asyncio
    async def test_get_hit_increments_hits(self, cache, mock_redis):
        """get() increments hit counter on cache hit."""
        mock_redis.get.return_value = orjson.dumps("value")

        await cache.get("k")

        assert cache._stats["hits"] == 1

    @pytest.mark.asyncio
    async def test_get_redis_error_returns_none(self, cache, mock_redis):
        """get() returns None when Redis raises an exception."""
        mock_redis.get.side_effect = ConnectionError("down")

        result = await cache.get("k")

        assert result is None
        assert cache._stats["misses"] == 1


class TestCacheServiceSet:
    """Tests for CacheService.set()."""

    @pytest.mark.asyncio
    async def test_set_stores_serialized_value(self, cache, mock_redis):
        """set() serializes value with orjson and calls setex."""
        result = await cache.set("k", {"a": 1}, ttl=120)

        assert result is True
        mock_redis.setex.assert_awaited_once()
        args = mock_redis.setex.call_args
        assert args[0][0] == "k"
        assert args[0][1] == 120

    @pytest.mark.asyncio
    async def test_set_uses_default_ttl(self, cache, mock_redis):
        """set() falls back to CacheConfig.TTL_MEDIUM when no TTL given."""
        await cache.set("k", "v")

        args = mock_redis.setex.call_args
        assert args[0][1] == CacheConfig.TTL_MEDIUM

    @pytest.mark.asyncio
    async def test_set_increments_sets_counter(self, cache, mock_redis):
        """set() increments the 'sets' stat."""
        await cache.set("k", "v")

        assert cache._stats["sets"] == 1

    @pytest.mark.asyncio
    async def test_set_redis_error_returns_false(self, cache, mock_redis):
        """set() returns False when Redis raises."""
        mock_redis.setex.side_effect = ConnectionError("down")

        result = await cache.set("k", "v")

        assert result is False


class TestCacheServiceDelete:
    """Tests for CacheService.delete()."""

    @pytest.mark.asyncio
    async def test_delete_existing_key(self, cache, mock_redis):
        """delete() returns True when key existed."""
        mock_redis.delete.return_value = 1

        result = await cache.delete("k")

        assert result is True
        assert cache._stats["deletes"] == 1

    @pytest.mark.asyncio
    async def test_delete_missing_key(self, cache, mock_redis):
        """delete() returns False when key did not exist."""
        mock_redis.delete.return_value = 0

        result = await cache.delete("missing")

        assert result is False


class TestCacheServiceExists:
    """Tests for CacheService.exists()."""

    @pytest.mark.asyncio
    async def test_exists_true(self, cache, mock_redis):
        """exists() returns True when key is present."""
        mock_redis.exists.return_value = 1

        assert await cache.exists("k") is True

    @pytest.mark.asyncio
    async def test_exists_false(self, cache, mock_redis):
        """exists() returns False when key is absent."""
        mock_redis.exists.return_value = 0

        assert await cache.exists("k") is False

    @pytest.mark.asyncio
    async def test_exists_error_returns_false(self, cache, mock_redis):
        """exists() returns False when Redis raises."""
        mock_redis.exists.side_effect = ConnectionError("down")

        assert await cache.exists("k") is False


class TestCacheServiceGetOrSet:
    """Tests for CacheService.get_or_set()."""

    @pytest.mark.asyncio
    async def test_get_or_set_cache_hit(self, cache, mock_redis):
        """get_or_set() returns cached value without calling factory."""
        mock_redis.get.return_value = orjson.dumps({"cached": True})
        factory = AsyncMock(return_value={"computed": True})

        result = await cache.get_or_set("k", factory, ttl=60)

        assert result == {"cached": True}
        factory.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_or_set_cache_miss_async_factory(self, cache, mock_redis):
        """get_or_set() calls async factory and stores result on miss."""
        mock_redis.get.return_value = None
        factory = AsyncMock(return_value={"computed": True})

        result = await cache.get_or_set("k", factory, ttl=60)

        assert result == {"computed": True}
        factory.assert_awaited_once()
        mock_redis.setex.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_or_set_cache_miss_sync_factory(self, cache, mock_redis):
        """get_or_set() works with a sync factory callable."""
        mock_redis.get.return_value = None
        factory = MagicMock(return_value=42)

        result = await cache.get_or_set("k", factory, ttl=60)

        assert result == 42
        factory.assert_called_once()


class TestCacheStats:
    """Tests for cache statistics."""

    @pytest.mark.asyncio
    async def test_get_stats_initial(self, cache):
        """Stats start at zero."""
        stats = cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate_percent"] == 0.0

    @pytest.mark.asyncio
    async def test_get_stats_after_operations(self, cache, mock_redis):
        """Stats accurately reflect operations."""
        mock_redis.get.side_effect = [orjson.dumps("v"), None]

        await cache.get("hit_key")
        await cache.get("miss_key")

        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate_percent"] == 50.0


class TestGetCacheSingleton:
    """Tests for get_cache / set_cache module-level accessors."""

    def test_get_cache_returns_none_by_default(self):
        """get_cache() returns None before set_cache() is called."""
        with patch("app.core.cache._cache", None):
            assert get_cache() is None

    def test_set_and_get_cache(self):
        """set_cache() stores instance retrievable by get_cache()."""
        mock_svc = MagicMock(spec=CacheService)
        with patch("app.core.cache._cache", None):
            set_cache(mock_svc)
            from app.core.cache import _cache
            assert _cache is mock_svc
