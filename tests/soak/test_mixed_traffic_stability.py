from __future__ import annotations

import asyncio
import json
import os
import time

import httpx
import pytest

from tests.platform_harness import (
    get_admin_access_token,
    get_admin_auth_headers,
    get_app_base_url,
    get_caddy_base_url,
    get_env_bool,
    get_env_float,
    get_env_int,
    get_websocket_url,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.live, pytest.mark.soak, pytest.mark.slow]


def _record_http_failure(
    failures: list[str],
    *,
    label: str,
    response: httpx.Response,
    allowed_statuses: set[int],
) -> None:
    if response.status_code not in allowed_statuses:
        failures.append(f"{label} returned {response.status_code}: {response.text[:200]}")


async def test_mixed_traffic_soak_stays_within_error_budget() -> None:
    websockets = pytest.importorskip("websockets", reason="Soak websocket coverage requires the websockets package")
    iteration_count = get_env_int("SOAK_ITERATIONS", 20)
    duration_seconds = get_env_float("SOAK_DURATION_SECONDS", 0.0)
    pause_seconds = get_env_float("SOAK_PAUSE_SECONDS", 1.0)
    max_error_rate = get_env_float("SOAK_MAX_ERROR_RATE", 0.05)
    include_worker_path = get_env_bool("SOAK_INCLUDE_WORKER_PATH", True)
    worker_every_iterations = max(1, get_env_int("SOAK_WORKER_EVERY_N_ITERATIONS", 5))
    worker_timeout = get_env_int("SOAK_WORKER_TIMEOUT", 45)
    worker_tool = os.getenv("SOAK_TOOL_ID", "whatweb")
    worker_target = os.getenv("SOAK_TOOL_TARGET_URL", "http://caddy")

    failures: list[str] = []
    total_operations = 0
    worker_runs = 0

    async with (
        httpx.AsyncClient(base_url=get_app_base_url(), timeout=worker_timeout + 15.0) as app_client,
        httpx.AsyncClient(base_url=get_caddy_base_url(), timeout=15.0) as caddy_client,
    ):
        auth_headers = await get_admin_auth_headers(app_client)
        access_token = await get_admin_access_token(app_client)
        websocket_url = f"{get_websocket_url()}?token={access_token}"
        started = time.perf_counter()
        iteration = 0

        while True:
            if duration_seconds > 0:
                if iteration > 0 and (time.perf_counter() - started) >= duration_seconds:
                    break
            elif iteration >= iteration_count:
                break

            iteration += 1

            total_operations += 1
            health_response = await caddy_client.get("/api/health")
            _record_http_failure(failures, label="caddy-health", response=health_response, allowed_statuses={200})

            total_operations += 1
            setup_response = await app_client.get("/api/v1/auth/setup/status")
            _record_http_failure(failures, label="app-setup-status", response=setup_response, allowed_statuses={200})

            total_operations += 1
            auth_me_response = await app_client.get("/api/v1/auth/me", headers=auth_headers)
            _record_http_failure(failures, label="app-auth-me", response=auth_me_response, allowed_statuses={200})

            total_operations += 1
            try:
                async with websockets.connect(websocket_url, close_timeout=5, open_timeout=10) as websocket:
                    await websocket.send(json.dumps({"type": "ping"}))
                    payload = json.loads(await asyncio.wait_for(websocket.recv(), timeout=5.0))
                    if payload.get("type") != "pong":
                        failures.append(f"websocket returned unexpected payload: {payload}")
            except Exception as exc:  # pragma: no cover - live harness error capture
                failures.append(f"websocket failed: {exc.__class__.__name__}")

            if include_worker_path and iteration % worker_every_iterations == 0:
                total_operations += 1
                worker_runs += 1
                worker_response = await app_client.post(
                    f"/api/v1/tools/{worker_tool}/test",
                    headers=auth_headers,
                    json={
                        "target": worker_target,
                        "args": {"flags": "-a 1"},
                        "timeout": worker_timeout,
                    },
                )
                if worker_response.status_code != 200:
                    failures.append(f"worker-tool returned {worker_response.status_code}: {worker_response.text[:200]}")
                else:
                    worker_body = worker_response.json()
                    if not worker_body.get("success"):
                        failures.append(f"worker-tool reported failure: {worker_body}")

            await asyncio.sleep(pause_seconds)

    error_rate = len(failures) / max(total_operations, 1)

    if include_worker_path and iteration >= worker_every_iterations:
        assert worker_runs > 0

    assert error_rate <= max_error_rate, (
        f"error_rate={error_rate:.3f} exceeded max_error_rate={max_error_rate:.3f}; "
        f"failures={failures[:10]} total_operations={total_operations}"
    )
