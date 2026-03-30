from __future__ import annotations

import asyncio
import os
import time

import httpx
import pytest

from tests.platform_harness import get_admin_auth_headers, get_app_base_url, get_env_float, get_env_int

pytestmark = [pytest.mark.asyncio, pytest.mark.live, pytest.mark.load]


async def test_concurrent_tool_worker_execution_returns_usable_results() -> None:
    request_count = get_env_int("LOAD_TEST_TOOL_CONCURRENCY_REQUESTS", 3)
    max_wall_seconds = get_env_float("LOAD_TEST_TOOL_CONCURRENCY_MAX_WALL_SECONDS", 60.0)
    timeout_seconds = get_env_int("LOAD_TEST_TOOL_CONCURRENCY_TIMEOUT", 45)
    tool_id = os.getenv("LOAD_TEST_TOOL_CONCURRENCY_TOOL", "whatweb")
    target = os.getenv("LOAD_TEST_TOOL_CONCURRENCY_TARGET", "http://caddy")

    async with httpx.AsyncClient(base_url=get_app_base_url(), timeout=timeout_seconds + 15.0) as client:
        headers = await get_admin_auth_headers(client)

        async def run_once() -> httpx.Response:
            return await client.post(
                f"/api/tools/{tool_id}/test",
                headers=headers,
                json={
                    "target": target,
                    "args": {"flags": "-a 1"},
                    "timeout": timeout_seconds,
                },
            )

        started = time.perf_counter()
        responses = await asyncio.gather(*(run_once() for _ in range(request_count)))
        wall_time = time.perf_counter() - started

    assert wall_time <= max_wall_seconds

    for response in responses:
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["tool_id"] == tool_id
        assert body["success"] is True
        assert body["exit_code"] == 0
        assert body["command_info"]["base_command"]
        assert (
            body["parsed_findings_count"] > 0
            or bool(body["stdout"].strip())
            or bool(body["stderr"].strip())
        ), body