from __future__ import annotations

import uuid

import httpx
import pytest

from tests.platform_harness import (
    ensure_admin_setup,
    ensure_platform_targets_available,
    get_app_base_url,
    get_app_replica_base_url,
    get_env_int,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.live, pytest.mark.load]


@pytest.fixture(scope="session", autouse=True)
def ensure_replica_targets_available() -> None:
    ensure_platform_targets_available(
        ("app", get_app_base_url()),
        ("app-replica", get_app_replica_base_url()),
        helper_command="./tests/run_load_tests.sh load",
    )


async def test_login_rate_limit_state_is_shared_across_app_replicas() -> None:
    expected_limit = get_env_int("LOAD_TEST_SHARED_LOGIN_EXPECTED_LIMIT", 5)
    primary_burst_count = max(1, expected_limit - 1)
    username = f"shared-limit-{uuid.uuid4().hex[:8]}"

    async with (
        httpx.AsyncClient(base_url=get_app_base_url(), timeout=15.0) as app_client,
        httpx.AsyncClient(base_url=get_app_replica_base_url(), timeout=15.0) as replica_client,
    ):
        await ensure_admin_setup(app_client)

        primary_responses = []
        for _ in range(primary_burst_count):
            primary_responses.append(
                await app_client.post(
                    "/api/auth/token",
                    data={"username": username, "password": "WrongPass123!"},
                )
            )

        replica_allowed = await replica_client.post(
            "/api/auth/token",
            data={"username": username, "password": "WrongPass123!"},
        )
        replica_throttled = await replica_client.post(
            "/api/auth/token",
            data={"username": username, "password": "WrongPass123!"},
        )
        app_throttled = await app_client.post(
            "/api/auth/token",
            data={"username": username, "password": "WrongPass123!"},
        )

    assert [response.status_code for response in primary_responses] == [401] * primary_burst_count
    assert replica_allowed.status_code == 401, replica_allowed.text
    assert replica_throttled.status_code == 429, replica_throttled.text
    assert app_throttled.status_code == 429, app_throttled.text

    throttled_body = replica_throttled.json()
    assert throttled_body["error"] == "RATE_LIMIT_EXCEEDED"
    assert throttled_body["retry_after_seconds"] > 0
