from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Awaitable, Callable

import httpx
import jwt
import pytest


def get_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


def get_env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value else default


def get_app_base_url() -> str:
    return os.getenv("LOAD_TEST_APP_URL", "http://127.0.0.1:15000")


def get_caddy_base_url() -> str:
    return os.getenv("LOAD_TEST_CADDY_URL", "http://127.0.0.1:15080")


def get_admin_username() -> str:
    return os.getenv("LOAD_TEST_ADMIN_USERNAME", "admin")


def get_admin_email() -> str:
    return os.getenv("LOAD_TEST_ADMIN_EMAIL", "admin@spectra.local")


def get_admin_password() -> str:
    return os.getenv("LOAD_TEST_ADMIN_PASSWORD", "Admin123!x")


def _healthcheck_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/api/health"


def ensure_platform_targets_available(*targets: tuple[str, str], helper_command: str) -> None:
    failures: list[str] = []

    with httpx.Client(timeout=5.0, follow_redirects=True) as client:
        for label, base_url in targets:
            try:
                client.get(_healthcheck_url(base_url))
            except httpx.HTTPError as exc:
                failures.append(f"{label} at {base_url} is unreachable ({exc.__class__.__name__})")

    if failures:
        pytest.skip(
            "These tests require a reachable live stack; "
            f"use {helper_command} or start the stack manually. Preflight failed: {'; '.join(failures)}"
        )


def percentile(values: list[float], pct: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")

    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]

    rank = (len(ordered) - 1) * (pct / 100.0)
    low_index = int(rank)
    high_index = min(low_index + 1, len(ordered) - 1)
    fraction = rank - low_index
    return ordered[low_index] + (ordered[high_index] - ordered[low_index]) * fraction


async def ensure_admin_setup(client: httpx.AsyncClient) -> None:
    status_response = await client.get("/api/auth/setup/status")
    assert status_response.status_code == 200, status_response.text

    if status_response.json().get("is_setup"):
        return

    setup_response = await client.post(
        "/api/auth/setup",
        json={
            "user": {
                "username": get_admin_username(),
                "email": get_admin_email(),
                "password": get_admin_password(),
            },
            "allow_registration": True,
        },
    )
    assert setup_response.status_code == 200, setup_response.text


async def get_admin_auth_headers(client: httpx.AsyncClient) -> dict[str, str]:
    await ensure_admin_setup(client)
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": get_admin_username(),
            "role": "operator",
            "is_superuser": True,
            "exp": now + timedelta(minutes=30),
            "iat": now,
            "type": "access",
        },
        os.getenv("LOAD_TEST_JWT_SECRET_KEY", "test-secret-key-for-testing"),
        algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
    )
    return {"Authorization": f"Bearer {token}"}


@dataclass(slots=True)
class LatencySummary:
    total_requests: int
    success_count: int
    durations_ms: list[float]
    status_codes: list[int]
    error_messages: list[str]

    @property
    def error_rate(self) -> float:
        return (self.total_requests - self.success_count) / self.total_requests

    @property
    def p50_ms(self) -> float:
        return percentile(self.durations_ms, 50)

    @property
    def p95_ms(self) -> float:
        return percentile(self.durations_ms, 95)

    def describe(self) -> str:
        return (
            f"statuses={self.status_codes} success={self.success_count}/{self.total_requests} "
            f"error_rate={self.error_rate:.3f} p50_ms={self.p50_ms:.1f} p95_ms={self.p95_ms:.1f}"
        )


async def collect_latency_summary(
    request_factory: Callable[[int], Awaitable[httpx.Response]],
    *,
    total_requests: int,
    concurrency: int,
) -> LatencySummary:
    semaphore = asyncio.Semaphore(concurrency)
    durations_ms: list[float] = []
    status_codes: list[int] = []
    error_messages: list[str] = []

    async def run_once(index: int) -> None:
        async with semaphore:
            started = time.perf_counter()
            try:
                response = await request_factory(index)
            except httpx.HTTPError as exc:
                durations_ms.append((time.perf_counter() - started) * 1000.0)
                status_codes.append(599)
                error_messages.append(str(exc))
                return

            durations_ms.append((time.perf_counter() - started) * 1000.0)
            status_codes.append(response.status_code)
            if response.status_code >= 400:
                error_messages.append(f"{response.status_code}: {response.text[:200]}")

    await asyncio.gather(*(run_once(index) for index in range(total_requests)))

    success_count = sum(1 for status_code in status_codes if status_code < 400)
    return LatencySummary(
        total_requests=total_requests,
        success_count=success_count,
        durations_ms=durations_ms,
        status_codes=status_codes,
        error_messages=error_messages,
    )