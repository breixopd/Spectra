from __future__ import annotations

import httpx
import pytest

from tests.platform_harness import (
    collect_latency_summary,
    ensure_admin_setup,
    get_admin_auth_headers,
    get_app_base_url,
    get_env_float,
    get_env_int,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.live, pytest.mark.performance]

DEFAULT_THRESHOLDS = {
    "HEALTH": (250.0, 900.0),
    "SETUP_STATUS": (350.0, 1000.0),
    "AUTH_ME": (500.0, 1400.0),
}


def _threshold(prefix: str, suffix: str, default: float) -> float:
    return get_env_float(f"PERF_{prefix}_{suffix}", default)


def _route_requests(prefix: str) -> int:
    return get_env_int(f"PERF_{prefix}_REQUESTS", get_env_int("PERF_REQUESTS", 24))


def _route_concurrency(prefix: str) -> int:
    return get_env_int(f"PERF_{prefix}_CONCURRENCY", get_env_int("PERF_CONCURRENCY", 6))


@pytest.mark.parametrize(
    ("prefix", "path", "requires_auth"),
    [
        ("HEALTH", "/api/health", False),
        ("SETUP_STATUS", "/api/v1/auth/setup/status", False),
        ("AUTH_ME", "/api/v1/auth/me", True),
    ],
)
async def test_core_routes_meet_lenient_latency_thresholds(prefix: str, path: str, requires_auth: bool) -> None:
    p50_default, p95_default = DEFAULT_THRESHOLDS[prefix]
    p50_limit = _threshold(prefix, "P50_MS", p50_default)
    p95_limit = _threshold(prefix, "P95_MS", p95_default)
    max_error_rate = _threshold(prefix, "MAX_ERROR_RATE", get_env_float("PERF_MAX_ERROR_RATE", 0.0))
    request_count = _route_requests(prefix)
    concurrency = _route_concurrency(prefix)

    async with httpx.AsyncClient(base_url=get_app_base_url(), timeout=15.0) as client:
        await ensure_admin_setup(client)
        headers = await get_admin_auth_headers(client) if requires_auth else {}

        summary = await collect_latency_summary(
            lambda _: client.get(path, headers=headers),
            total_requests=request_count,
            concurrency=concurrency,
        )

    assert summary.error_rate <= max_error_rate, summary.describe()
    assert summary.p50_ms <= p50_limit, summary.describe()
    assert summary.p95_ms <= p95_limit, summary.describe()
