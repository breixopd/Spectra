"""RedisCache.set_nx behaviour (mocked client)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from spectra_platform.infrastructure.redis_client import RedisCache


@pytest.mark.asyncio
async def test_set_nx_returns_false_when_key_exists() -> None:
    cache = RedisCache.__new__(RedisCache)
    fake_redis = MagicMock()
    fake_redis.set = AsyncMock(return_value=None)
    cache._client = fake_redis
    assert await cache.set_nx("k", ttl_seconds=60, value="1") is False


@pytest.mark.asyncio
async def test_set_nx_returns_true_on_success() -> None:
    cache = RedisCache.__new__(RedisCache)
    fake_redis = MagicMock()
    fake_redis.set = AsyncMock(return_value=True)
    cache._client = fake_redis
    assert await cache.set_nx("k", ttl_seconds=60) is True


@pytest.mark.asyncio
async def test_set_nx_no_client_returns_true() -> None:
    cache = RedisCache.__new__(RedisCache)
    cache._client = None
    assert await cache.set_nx("k", ttl_seconds=60) is True
