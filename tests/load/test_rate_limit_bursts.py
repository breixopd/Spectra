from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest

from tests.platform_harness import (
    ensure_admin_setup,
    get_app_base_url,
    get_caddy_base_url,
    get_env_int,
    recovery_window_tests_enabled,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.live, pytest.mark.load]


async def test_direct_app_login_burst_returns_structured_429() -> None:
    expected_limit = get_env_int("LOAD_TEST_LOGIN_EXPECTED_LIMIT", 5)

    async with httpx.AsyncClient(base_url=get_app_base_url(), timeout=15.0) as client:
        await ensure_admin_setup(client)

        responses = []
        for _ in range(expected_limit + 1):
            responses.append(
                await client.post(
                    "/api/auth/token",
                    data={"username": "missing-user", "password": "WrongPass123!"},
                )
            )

    assert [response.status_code for response in responses[:-1]] == [401] * expected_limit

    throttled = responses[-1]
    assert throttled.status_code == 429
    assert throttled.headers.get("Retry-After")
    assert throttled.headers.get("X-RateLimit-Remaining") == "0"
    assert throttled.headers.get("X-RateLimit-Limit")

    body = throttled.json()
    assert body["error"] == "RATE_LIMIT_EXCEEDED"
    assert body["retry_after_seconds"] > 0
    assert "Rate limit exceeded" in body["message"]


async def test_direct_app_public_registration_burst_hits_limit() -> None:
    expected_limit = get_env_int("LOAD_TEST_PUBLIC_REGISTER_EXPECTED_LIMIT", 3)
    run_id = uuid.uuid4().hex[:8]

    async with httpx.AsyncClient(base_url=get_app_base_url(), timeout=15.0) as client:
        await ensure_admin_setup(client)

        responses = []
        for attempt in range(expected_limit + 1):
            responses.append(
                await client.post(
                    "/api/public/register",
                    json={
                        "username": f"load-user-{run_id}-{attempt}",
                        "email": f"load-user-{run_id}-{attempt}@example.com",
                        "password": "StrongPass123!",
                    },
                )
            )

    assert [response.status_code for response in responses[:-1]] == [201] * expected_limit
    throttled = responses[-1]
    assert throttled.status_code == 429
    assert throttled.json()["error"] == "RATE_LIMIT_EXCEEDED"


async def test_caddy_edge_burst_triggers_before_direct_app_limit() -> None:
    request_count = get_env_int("LOAD_TEST_CADDY_SETUP_STATUS_REQUESTS", 12)
    recovery_wait_seconds = get_env_int("LOAD_TEST_CADDY_RECOVERY_WAIT_SECONDS", 65)
    recovery_grace_seconds = get_env_int("LOAD_TEST_CADDY_RECOVERY_GRACE_SECONDS", 2)

    async with (
        httpx.AsyncClient(base_url=get_app_base_url(), timeout=15.0) as app_client,
        httpx.AsyncClient(base_url=get_caddy_base_url(), timeout=15.0) as caddy_client,
    ):
        await ensure_admin_setup(app_client)

        proxied_responses = []
        for _ in range(request_count):
            proxied_responses.append(await caddy_client.get("/api/auth/setup/status"))

        direct_responses = []
        for _ in range(request_count):
            direct_responses.append(await app_client.get("/api/auth/setup/status"))

    assert any(response.status_code == 429 for response in proxied_responses)
    assert proxied_responses[-1].status_code == 429
    assert all(response.status_code == 200 for response in direct_responses)

    if recovery_window_tests_enabled():
        wait_seconds = int(proxied_responses[-1].headers.get("Retry-After") or recovery_wait_seconds)
        await asyncio.sleep(wait_seconds + recovery_grace_seconds)

        async with httpx.AsyncClient(base_url=get_caddy_base_url(), timeout=15.0) as caddy_client:
            recovered = await caddy_client.get("/api/auth/setup/status")

        assert recovered.status_code == 200, recovered.text
