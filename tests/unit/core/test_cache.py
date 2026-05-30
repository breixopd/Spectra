"""Unit tests for app.infrastructure.cache module (PostgreSQL-backed)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from spectra_infra.cache import CacheService, _json_dumps, get_cache, set_cache
from spectra_persistence.models.infrastructure import CacheEntry


@pytest_asyncio.fixture
async def db_session_maker():
    """Create an in-memory SQLite async engine and session maker for tests."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        # Only create cache DDL — full Base.metadata hits duplicate explicit-vs-implicit
        # indexes on several models when running create_all against SQLite.
        await conn.run_sync(CacheEntry.__table__.create, checkfirst=True)

    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield maker

    await engine.dispose()


@pytest_asyncio.fixture
async def cache(db_session_maker):
    """Provide a CacheService backed by in-memory SQLite."""
    return CacheService(session_maker=db_session_maker)


class TestCacheServiceGet:
    """Tests for CacheService.get()."""

    @pytest.mark.asyncio
    async def test_get_returns_deserialized_value(self, cache, db_session_maker):
        """get() deserializes and returns cached data."""
        payload = {"foo": "bar"}
        await cache.set("key1", payload, ttl=300)

        result = await cache.get("key1")

        assert result == payload

    @pytest.mark.asyncio
    async def test_get_miss_returns_none(self, cache):
        """get() returns None and increments misses on cache miss."""
        result = await cache.get("missing")

        assert result is None
        assert cache._stats["misses"] == 1

    @pytest.mark.asyncio
    async def test_get_hit_increments_hits(self, cache):
        """get() increments hit counter on cache hit."""
        await cache.set("k", "value")

        await cache.get("k")

        assert cache._stats["hits"] == 1

    @pytest.mark.asyncio
    async def test_get_expired_returns_none(self, cache, db_session_maker):
        """get() returns None for expired entries."""
        # Insert an already-expired entry directly
        async with db_session_maker() as session:
            entry = CacheEntry(
                key="expired_key",
                value=_json_dumps("old_value"),
                expires_at=datetime.now(UTC) - timedelta(seconds=10),
                created_at=datetime.now(UTC),
            )
            session.add(entry)
            await session.commit()

        result = await cache.get("expired_key")

        assert result is None
        assert cache._stats["misses"] == 1

    @pytest.mark.asyncio
    async def test_get_db_error_returns_none(self, cache):
        """get() returns None when DB raises an exception."""
        cache._session_maker = MagicMock(side_effect=ConnectionError("down"))

        result = await cache.get("k")

        assert result is None
        assert cache._stats["misses"] == 1


class TestCacheServiceSet:
    """Tests for CacheService.set()."""

    @pytest.mark.asyncio
    async def test_set_stores_value(self, cache):
        """set() stores value and retrieves it."""
        result = await cache.set("k", {"a": 1}, ttl=120)

        assert result is True
        retrieved = await cache.get("k")
        assert retrieved == {"a": 1}

    @pytest.mark.asyncio
    async def test_set_uses_default_ttl(self, cache):
        """set() works with default TTL."""
        result = await cache.set("k", "v")

        assert result is True
        assert cache._stats["sets"] == 1

    @pytest.mark.asyncio
    async def test_set_increments_sets_counter(self, cache):
        """set() increments the 'sets' stat."""
        await cache.set("k", "v")

        assert cache._stats["sets"] == 1

    @pytest.mark.asyncio
    async def test_set_upsert_overwrites(self, cache):
        """set() overwrites existing keys."""
        await cache.set("k", "first")
        await cache.set("k", "second")

        result = await cache.get("k")
        assert result == "second"

    @pytest.mark.asyncio
    async def test_set_db_error_returns_false(self, cache):
        """set() returns False when DB raises."""
        cache._session_maker = MagicMock(side_effect=ConnectionError("down"))

        result = await cache.set("k", "v")

        assert result is False


class TestCacheServiceDelete:
    """Tests for CacheService.delete()."""

    @pytest.mark.asyncio
    async def test_delete_existing_key(self, cache):
        """delete() returns True when key existed."""
        await cache.set("k", "v")

        result = await cache.delete("k")

        assert result is True
        assert cache._stats["deletes"] == 1

    @pytest.mark.asyncio
    async def test_delete_missing_key(self, cache):
        """delete() returns False when key did not exist."""
        result = await cache.delete("missing")

        assert result is False


class TestCacheServiceDeletePattern:
    """Tests for CacheService.delete_pattern()."""

    @pytest.mark.asyncio
    async def test_delete_pattern_removes_matching(self, cache):
        """delete_pattern() removes keys matching glob pattern."""
        await cache.set("cache:tool:a", "1")
        await cache.set("cache:tool:b", "2")
        await cache.set("cache:other:c", "3")

        count = await cache.delete_pattern("cache:tool:*")

        assert count == 2
        assert await cache.exists("cache:other:c") is True
        assert await cache.exists("cache:tool:a") is False


class TestCacheServiceExists:
    """Tests for CacheService.exists()."""

    @pytest.mark.asyncio
    async def test_exists_true(self, cache):
        """exists() returns True when key is present."""
        await cache.set("k", "v")

        assert await cache.exists("k") is True

    @pytest.mark.asyncio
    async def test_exists_false(self, cache):
        """exists() returns False when key is absent."""
        assert await cache.exists("k") is False

    @pytest.mark.asyncio
    async def test_exists_expired_returns_false(self, cache, db_session_maker):
        """exists() returns False for expired entries."""
        async with db_session_maker() as session:
            entry = CacheEntry(
                key="expired",
                value=_json_dumps("val"),
                expires_at=datetime.now(UTC) - timedelta(seconds=10),
                created_at=datetime.now(UTC),
            )
            session.add(entry)
            await session.commit()

        assert await cache.exists("expired") is False

    @pytest.mark.asyncio
    async def test_exists_error_returns_false(self, cache):
        """exists() returns False when DB raises."""
        cache._session_maker = MagicMock(side_effect=ConnectionError("down"))

        assert await cache.exists("k") is False


class TestCacheServiceGetOrSet:
    """Tests for CacheService.get_or_set()."""

    @pytest.mark.asyncio
    async def test_get_or_set_cache_hit(self, cache):
        """get_or_set() returns cached value without calling factory."""
        await cache.set("k", {"cached": True})
        factory = AsyncMock(return_value={"computed": True})

        result = await cache.get_or_set("k", factory, ttl=60)

        assert result == {"cached": True}
        factory.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_or_set_cache_miss_async_factory(self, cache):
        """get_or_set() calls async factory and stores result on miss."""
        factory = AsyncMock(return_value={"computed": True})

        result = await cache.get_or_set("k", factory, ttl=60)

        assert result == {"computed": True}
        factory.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_or_set_cache_miss_sync_factory(self, cache):
        """get_or_set() works with a sync factory callable."""
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
    async def test_get_stats_after_operations(self, cache):
        """Stats accurately reflect operations."""
        await cache.set("hit_key", "v")
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
        with patch("spectra_infra.cache._cache", None):
            assert get_cache() is None

    def test_set_and_get_cache(self):
        """set_cache() stores instance retrievable by get_cache()."""
        mock_svc = MagicMock(spec=CacheService)
        with patch("spectra_infra.cache._cache", None):
            set_cache(mock_svc)
            from spectra_infra.cache import _cache

            assert _cache is mock_svc
