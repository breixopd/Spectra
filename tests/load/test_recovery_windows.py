from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest

from tests.platform_harness import (
    ensure_admin_setup,
    get_app_base_url,
    get_env_int,
    require_recovery_window_tests_enabled,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.live, pytest.mark.load, pytest.mark.slow]


def _wait_seconds(response: httpx.Response, *, env_name: str, default: int, grace_env_name: str) -> int:
    retry_after = response.headers.get("Retry-After")
    if retry_after and retry_after.isdigit():
        base_seconds = int(retry_after)
    else:
        body = response.json()
        base_seconds = int(body.get("retry_after_seconds", get_env_int(env_name, default)))
    return base_seconds + get_env_int(grace_env_name, 2)


async def test_direct_app_login_limit_recovers_after_window() -> None:
    require_recovery_window_tests_enabled()

    expected_limit = get_env_int("LOAD_TEST_LOGIN_EXPECTED_LIMIT", 5)
    username = f"recovery-missing-{uuid.uuid4().hex[:8]}"

    async with httpx.AsyncClient(base_url=get_app_base_url(), timeout=15.0) as client:
        await ensure_admin_setup(client)

        responses = []
        for _ in range(expected_limit + 1):
            responses.append(
                await client.post(
                    "/api/v1/auth/token",
                    data={"username": username, "password": "WrongPass123!"},
                )
            )

        throttled = responses[-1]
        assert throttled.status_code == 429

        await asyncio.sleep(
            _wait_seconds(
                throttled,
                env_name="LOAD_TEST_APP_RECOVERY_WAIT_SECONDS",
                default=65,
                grace_env_name="LOAD_TEST_APP_RECOVERY_GRACE_SECONDS",
            )
        )

        recovered = await client.post(
            "/api/v1/auth/token",
            data={"username": username, "password": "WrongPass123!"},
        )

    assert [response.status_code for response in responses[:-1]] == [401] * expected_limit
    assert recovered.status_code == 401, recovered.text
