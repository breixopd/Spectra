from __future__ import annotations

import httpx
import pytest

from app.core.security import create_password_reset_token
from tests.platform_harness import create_public_test_user, get_app_base_url, get_env_int

pytestmark = [pytest.mark.asyncio, pytest.mark.live, pytest.mark.load]


def _assert_structured_rate_limit(response: httpx.Response) -> None:
    assert response.status_code == 429
    assert response.headers.get("Retry-After")
    assert response.headers.get("X-RateLimit-Limit")
    assert response.headers.get("X-RateLimit-Remaining") == "0"

    body = response.json()
    assert body["error"] == "RATE_LIMIT_EXCEEDED"
    assert body["retry_after_seconds"] > 0
    assert "Rate limit exceeded" in body["message"]


async def test_forgot_password_burst_returns_structured_429() -> None:
    expected_limit = get_env_int("LOAD_TEST_FORGOT_PASSWORD_EXPECTED_LIMIT", 3)

    async with httpx.AsyncClient(base_url=get_app_base_url(), timeout=15.0) as client:
        user = await create_public_test_user(client, prefix="load-reset-forgot")

        responses = []
        for _ in range(expected_limit + 1):
            responses.append(
                await client.post(
                    "/api/auth/forgot-password",
                    json={"email": user.email},
                )
            )

    assert [response.status_code for response in responses[:-1]] == [204] * expected_limit
    _assert_structured_rate_limit(responses[-1])


async def test_reset_password_burst_returns_structured_429() -> None:
    expected_limit = get_env_int("LOAD_TEST_RESET_PASSWORD_EXPECTED_LIMIT", 5)

    async with httpx.AsyncClient(base_url=get_app_base_url(), timeout=15.0) as client:
        user = await create_public_test_user(client, prefix="load-reset-apply")

        responses = []
        for attempt in range(expected_limit + 1):
            reset_token = create_password_reset_token(user.user_id)
            responses.append(
                await client.post(
                    "/api/auth/reset-password",
                    json={
                        "token": reset_token,
                        "new_password": f"ResetPass123!Aa{attempt}",
                    },
                )
            )

    assert [response.status_code for response in responses[:-1]] == [200] * expected_limit
    _assert_structured_rate_limit(responses[-1])