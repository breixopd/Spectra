from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Awaitable, Callable
from urllib.parse import urlsplit, urlunsplit

import httpx
import jwt
import pytest


def get_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


def get_env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value else default


def get_env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_app_base_url() -> str:
    return os.getenv("LOAD_TEST_APP_URL", "http://127.0.0.1:15000")


def get_app_replica_base_url() -> str:
    return os.getenv("LOAD_TEST_APP_REPLICA_URL", "http://127.0.0.1:15001")


def get_caddy_base_url() -> str:
    return os.getenv("LOAD_TEST_CADDY_URL", "http://127.0.0.1:15080")


def derive_websocket_url(base_url: str) -> str:
    parsed = urlsplit(base_url.rstrip("/"))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = parsed.path.rstrip("/")
    websocket_path = path if path.endswith("/ws") else f"{path}/ws" if path else "/ws"
    return urlunsplit((scheme, parsed.netloc, websocket_path, "", ""))


def get_websocket_url() -> str:
    return os.getenv("LOAD_TEST_WS_URL", derive_websocket_url(get_caddy_base_url()))


def get_admin_username() -> str:
    return os.getenv("LOAD_TEST_ADMIN_USERNAME", "admin")


def get_admin_email() -> str:
    return os.getenv("LOAD_TEST_ADMIN_EMAIL", "admin@spectra.local")


def get_admin_password() -> str:
    return os.getenv("LOAD_TEST_ADMIN_PASSWORD", "Admin123!x")


def _healthcheck_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/api/health"


def _platform_targets_skip_message(*, failures: list[str], helper_command: str) -> str:
    return (
        "These tests require a reachable live stack; "
        f"use {helper_command} or start the stack manually. Preflight failed: {'; '.join(failures)}"
    )


def ensure_platform_targets_available(*targets: tuple[str, str], helper_command: str) -> None:
    failures: list[str] = []

    with httpx.Client(timeout=5.0, follow_redirects=False) as client:
        for label, base_url in targets:
            health_url = _healthcheck_url(base_url)
            try:
                response = client.get(health_url)
            except httpx.HTTPError as exc:
                failures.append(f"{label} at {base_url} is unreachable ({exc.__class__.__name__})")
                continue

            if not response.is_success:
                failures.append(
                    f"{label} at {health_url} returned HTTP {response.status_code}"
                )

    if failures:
        pytest.skip(_platform_targets_skip_message(failures=failures, helper_command=helper_command))


def recovery_window_tests_enabled() -> bool:
    return get_env_bool("LOAD_TEST_ENABLE_RECOVERY_WINDOWS", False)


def require_recovery_window_tests_enabled() -> None:
    if recovery_window_tests_enabled():
        return
    pytest.skip(
        "Recovery-window assertions are disabled by default; "
        "set LOAD_TEST_ENABLE_RECOVERY_WINDOWS=1 to enable them."
    )


async def reset_rate_limit_state_if_requested() -> None:
    if not get_env_bool("LOAD_TEST_RESET_RATE_LIMIT_STATE", False):
        return

    storage_url = os.getenv("RATE_LIMIT_STORAGE", "")
    if not storage_url.startswith(("redis://", "rediss://")):
        return

    try:
        import redis.asyncio as redis
        from redis import exceptions as redis_exceptions
    except ImportError:
        pytest.skip(
            "Load test rate-limit reset was requested, but redis-py is unavailable in the test runner."
        )

    client = redis.from_url(storage_url, encoding="utf-8", decode_responses=True)
    try:
        await client.flushdb()
    except (
        redis_exceptions.ConnectionError,
        redis_exceptions.TimeoutError,
        redis_exceptions.RedisError,
    ) as exc:
        pytest.skip(
            "Load test isolation requires a reachable Redis rate-limit backend; "
            "use ./tests/run_load_tests.sh load or unset LOAD_TEST_RESET_RATE_LIMIT_STATE. "
            f"Preflight failed: {exc.__class__.__name__}"
        )
    finally:
        try:
            await client.aclose()
        except redis_exceptions.RedisError:
            pass


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


async def get_admin_access_token(client: httpx.AsyncClient) -> str:
    await ensure_admin_setup(client)
    now = datetime.now(UTC)
    return jwt.encode(
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


async def get_admin_auth_headers(client: httpx.AsyncClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {await get_admin_access_token(client)}"}


async def get_access_token_for_credentials(
    client: httpx.AsyncClient,
    *,
    username: str,
    password: str,
) -> str:
    response = await client.post(
        "/api/auth/token",
        data={"username": username, "password": password},
    )
    if response.status_code == 403 and "verify your email" in response.text.lower():
        pytest.skip(
            "Load user provisioning requires email verification to be disabled in the test stack."
        )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


async def get_auth_headers_for_credentials(
    client: httpx.AsyncClient,
    *,
    username: str,
    password: str,
) -> dict[str, str]:
    token = await get_access_token_for_credentials(client, username=username, password=password)
    return {"Authorization": f"Bearer {token}"}


async def get_current_profile(
    client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
) -> dict[str, object]:
    response = await client.get("/api/auth/me", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def resolve_admin_user_id(client: httpx.AsyncClient) -> str:
    profile = await get_current_profile(client, headers=await get_admin_auth_headers(client))
    return str(profile["id"])


@dataclass(slots=True)
class LoadTestUser:
    username: str
    email: str
    password: str
    user_id: str


async def create_public_test_user(
    client: httpx.AsyncClient,
    *,
    prefix: str = "load-user",
) -> LoadTestUser:
    await ensure_admin_setup(client)

    run_id = uuid.uuid4().hex[:10]
    username = f"{prefix}-{run_id}"
    email = f"{prefix}-{run_id}@example.com"
    password = f"StrongPass123!Aa{run_id[:2]}"

    response = await client.post(
        "/api/public/register",
        json={
            "username": username,
            "email": email,
            "password": password,
        },
    )
    assert response.status_code == 201, response.text

    headers = await get_auth_headers_for_credentials(client, username=username, password=password)
    profile = await get_current_profile(client, headers=headers)
    return LoadTestUser(
        username=username,
        email=email,
        password=password,
        user_id=str(profile["id"]),
    )


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