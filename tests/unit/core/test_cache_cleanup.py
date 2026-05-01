"""Tests for cache cleanup / purge_expired functionality."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from spectra_platform.infrastructure.cache import CacheConfig, CacheService


@pytest.fixture
def mock_session_maker():
    """Create a mock async session maker."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    maker = MagicMock(return_value=session)
    return maker, session


class TestCachePurgeExpired:
    """Test the purge_expired method of CacheService."""

    @pytest.mark.asyncio
    async def test_purge_expired_returns_count(self, mock_session_maker):
        maker, session = mock_session_maker
        result_mock = MagicMock()
        result_mock.rowcount = 5
        session.execute = AsyncMock(return_value=result_mock)
        session.commit = AsyncMock()

        cache = CacheService(session_maker=maker)
        count = await cache.purge_expired()
        assert count == 5
        session.execute.assert_awaited_once()
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_purge_expired_returns_zero_on_no_expired(self, mock_session_maker):
        maker, session = mock_session_maker
        result_mock = MagicMock()
        result_mock.rowcount = 0
        session.execute = AsyncMock(return_value=result_mock)
        session.commit = AsyncMock()

        cache = CacheService(session_maker=maker)
        count = await cache.purge_expired()
        assert count == 0

    @pytest.mark.asyncio
    async def test_purge_expired_handles_db_error(self, mock_session_maker):
        maker, session = mock_session_maker
        session.execute = AsyncMock(side_effect=OSError("db gone"))

        cache = CacheService(session_maker=maker)
        count = await cache.purge_expired()
        assert count == 0


class TestCacheStats:
    """Test cache statistics tracking."""

    @pytest.mark.asyncio
    async def test_get_stats_initial(self, mock_session_maker):
        maker, _ = mock_session_maker
        cache = CacheService(session_maker=maker)
        stats = cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["total_requests"] == 0
        assert stats["hit_rate_percent"] == 0.0

    @pytest.mark.asyncio
    async def test_stats_after_miss(self, mock_session_maker):
        maker, session = mock_session_maker
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        cache = CacheService(session_maker=maker)
        val = await cache.get("nonexistent")
        assert val is None
        stats = cache.get_stats()
        assert stats["misses"] == 1
        assert stats["hits"] == 0


class TestCacheConfig:
    """Test cache configuration constants."""

    def test_ttl_values(self):
        assert CacheConfig.TTL_SHORT == 60
        assert CacheConfig.TTL_MEDIUM == 300
        assert CacheConfig.TTL_LONG == 3600
        assert CacheConfig.TTL_DAY == 86400

    def test_prefix_values(self):
        assert CacheConfig.PREFIX_TOOL.startswith("cache:")
        assert CacheConfig.PREFIX_MISSION.startswith("cache:")
