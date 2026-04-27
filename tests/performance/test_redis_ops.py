"""Performance benchmarks for Redis operations."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from app.core.redis_client import RedisCache, RedisConnectionPool

pytestmark = [pytest.mark.asyncio, pytest.mark.live, pytest.mark.performance]


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


class TestRedisPingLatency:
    async def test_redis_ping_under_50ms(self) -> None:
        cache = RedisCache()
        if cache._client is None:
            pytest.skip("Redis not available")

        latencies = await _measure_latency(cache._client.ping, 50)
        assert latencies["p95_ms"] < 50, f"Redis ping p95 {latencies['p95_ms']}ms exceeds 50ms"
        await RedisConnectionPool.close_pool()


class TestRedisBulkThroughput:
    async def test_bulk_set_throughput(self) -> None:
        cache = RedisCache()
        if cache._client is None:
            pytest.skip("Redis not available")

        count = 500
        start = time.perf_counter()
        for i in range(count):
            await cache.set(f"perf:bulk:set:{i}", {"index": i}, ttl=60)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        ops_per_sec = count / (elapsed_ms / 1000.0)
        assert ops_per_sec > 50, f"Bulk set throughput {ops_per_sec:.1f} ops/s below 50"
        await RedisConnectionPool.close_pool()

    async def test_bulk_get_throughput(self) -> None:
        cache = RedisCache()
        if cache._client is None:
            pytest.skip("Redis not available")

        count = 500
        for i in range(count):
            await cache.set(f"perf:bulk:get:{i}", {"index": i}, ttl=60)

        start = time.perf_counter()
        for i in range(count):
            await cache.get(f"perf:bulk:get:{i}")
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        ops_per_sec = count / (elapsed_ms / 1000.0)
        assert ops_per_sec > 50, f"Bulk get throughput {ops_per_sec:.1f} ops/s below 50"
        await RedisConnectionPool.close_pool()


class TestRedisPatternDelete:
    async def test_pattern_delete_performance(self) -> None:
        cache = RedisCache()
        if cache._client is None:
            pytest.skip("Redis not available")

        prefix = "perf:pattern:del"
        count = 200
        for i in range(count):
            await cache.set(f"{prefix}:{i}", {"index": i}, ttl=300)

        start = time.perf_counter()
        deleted = await cache.delete_pattern(f"{prefix}:*")
        elapsed_ms = (time.perf_counter() - start) * 1000.0

        assert deleted == count, f"Expected {count} deletions, got {deleted}"
        assert elapsed_ms < 5000, f"Pattern delete took {elapsed_ms:.1f}ms, exceeds 5000ms"
        await RedisConnectionPool.close_pool()
