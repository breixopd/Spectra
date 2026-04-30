"""Performance benchmarks for cache operations (PostgreSQL vs Redis)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.infrastructure.cache import CacheService
from app.infrastructure.redis_client import RedisCache, RedisConnectionPool

pytestmark = [pytest.mark.asyncio, pytest.mark.live, pytest.mark.performance]


@pytest_asyncio.fixture
async def db_session_maker():
    """Use the live stack database session maker for cache performance tests."""
    database_url = settings.DATABASE_URL
    if hasattr(database_url, "get_secret_value"):
        database_url = database_url.get_secret_value()
    engine = create_async_engine(str(database_url), pool_pre_ping=False)
    try:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _warm_cache_pg(cache: CacheService, keys: list[str]) -> None:
    for key in keys:
        await cache.set(key, {"data": key}, ttl=300)


async def _warm_cache_redis(cache: RedisCache, keys: list[str]) -> None:
    for key in keys:
        await cache.set(key, {"data": key}, ttl=300)


async def _measure_latency(
    operation: Callable[[], Awaitable[Any]],
    iterations: int,
) -> dict[str, float]:
    durations: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        await operation()
        durations.append((time.perf_counter() - start) * 1000.0)
    durations.sort()
    n = len(durations)
    return {
        "p50_ms": durations[n // 2] if n % 2 else (durations[n // 2 - 1] + durations[n // 2]) / 2,
        "p95_ms": durations[int(n * 0.95)] if n > 1 else durations[0],
        "avg_ms": sum(durations) / n,
        "min_ms": durations[0],
        "max_ms": durations[-1],
    }


class TestCacheHitRateUnderLoad:
    async def test_pg_cache_hit_rate_1000_ops(self, db_session_maker) -> None:
        cache = CacheService(session_maker=db_session_maker)
        keys = [f"perf:hitrate:{i}" for i in range(100)]
        await _warm_cache_pg(cache, keys)

        hits = misses = 0
        for i in range(1000):
            key = keys[i % len(keys)]
            value = await cache.get(key)
            if value is not None:
                hits += 1
            else:
                misses += 1

        hit_rate = hits / (hits + misses)
        assert hit_rate >= 0.99, f"PG cache hit rate {hit_rate} below 99%"

    async def test_redis_cache_hit_rate_1000_ops(self) -> None:
        redis_cache = RedisCache()
        if redis_cache._client is None:
            pytest.skip("Redis not available")

        keys = [f"perf:hitrate:redis:{i}" for i in range(100)]
        await _warm_cache_redis(redis_cache, keys)

        hits = misses = 0
        for i in range(1000):
            key = keys[i % len(keys)]
            value = await redis_cache.get(key)
            if value is not None:
                hits += 1
            else:
                misses += 1

        hit_rate = hits / (hits + misses)
        assert hit_rate >= 0.99, f"Redis cache hit rate {hit_rate} below 99%"
        await RedisConnectionPool.close_pool()


class TestCacheLatencyComparison:
    async def test_pg_vs_redis_set_latency(self, db_session_maker) -> None:
        pg_cache = CacheService(session_maker=db_session_maker)
        redis_cache = RedisCache()
        iterations = 100

        pg_latencies = await _measure_latency(
            lambda: pg_cache.set(f"perf:latency:pg:{time.time()}", {"v": 1}, ttl=60),
            iterations,
        )

        redis_latencies = None
        if redis_cache._client is not None:
            redis_latencies = await _measure_latency(
                lambda: redis_cache.set(f"perf:latency:redis:{time.time()}", {"v": 1}, ttl=60),
                iterations,
            )
            await RedisConnectionPool.close_pool()

        assert pg_latencies["p95_ms"] < 5000, f"PG set p95 too high: {pg_latencies['p95_ms']}ms"
        if redis_latencies:
            assert redis_latencies["p95_ms"] < 5000, f"Redis set p95 too high: {redis_latencies['p95_ms']}ms"

    async def test_pg_vs_redis_get_latency(self, db_session_maker) -> None:
        pg_cache = CacheService(session_maker=db_session_maker)
        redis_cache = RedisCache()
        key = "perf:latency:get"
        await pg_cache.set(key, {"v": 1}, ttl=300)
        if redis_cache._client is not None:
            await redis_cache.set(key, {"v": 1}, ttl=300)

        iterations = 100
        pg_latencies = await _measure_latency(lambda: pg_cache.get(key), iterations)

        redis_latencies = None
        if redis_cache._client is not None:
            redis_latencies = await _measure_latency(lambda: redis_cache.get(key), iterations)
            await RedisConnectionPool.close_pool()

        assert pg_latencies["p95_ms"] < 5000, f"PG get p95 too high: {pg_latencies['p95_ms']}ms"
        if redis_latencies:
            assert redis_latencies["p95_ms"] < 5000, f"Redis get p95 too high: {redis_latencies['p95_ms']}ms"


class TestCacheTTLAccuracy:
    async def test_pg_ttl_expires_within_tolerance(self, db_session_maker) -> None:
        cache = CacheService(session_maker=db_session_maker)
        key = "perf:ttl:pg"
        ttl_seconds = 2
        await cache.set(key, {"data": 1}, ttl=ttl_seconds)

        assert await cache.get(key) is not None
        await asyncio.sleep(ttl_seconds + 1)
        assert await cache.get(key) is None

    async def test_redis_ttl_expires_within_tolerance(self) -> None:
        redis_cache = RedisCache()
        if redis_cache._client is None:
            pytest.skip("Redis not available")

        key = "perf:ttl:redis"
        ttl_seconds = 2
        await redis_cache.set(key, {"data": 1}, ttl=ttl_seconds)

        assert await redis_cache.get(key) is not None
        await asyncio.sleep(ttl_seconds + 1)
        assert await redis_cache.get(key) is None
        await RedisConnectionPool.close_pool()
