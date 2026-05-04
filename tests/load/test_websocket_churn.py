from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from tests.platform_harness import (
    get_admin_access_token,
    get_app_base_url,
    get_env_float,
    get_env_int,
    get_websocket_url,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.live, pytest.mark.load]


async def test_websocket_repeated_connect_disconnect_handles_ping_pong() -> None:
    websockets = pytest.importorskip("websockets", reason="WebSocket churn tests require the websockets package")
    connection_count = get_env_int("LOAD_TEST_WS_CHURN_CONNECTIONS", 20)

    async with httpx.AsyncClient(base_url=get_app_base_url(), timeout=15.0) as client:
        token = await get_admin_access_token(client)
        websocket_url = f"{get_websocket_url()}?token={token}"

        for _ in range(connection_count):
            async with websockets.connect(websocket_url, close_timeout=5, open_timeout=10) as websocket:
                await websocket.send(json.dumps({"type": "ping"}))
                payload = json.loads(await asyncio.wait_for(websocket.recv(), timeout=5.0))
                assert payload["type"] == "pong"


async def test_websocket_message_burst_returns_error_frame_without_closing_socket() -> None:
    websockets = pytest.importorskip("websockets", reason="WebSocket burst tests require the websockets package")
    burst_messages = get_env_int("LOAD_TEST_WS_BURST_MESSAGES", 14)
    post_burst_reset_seconds = get_env_float("LOAD_TEST_WS_BURST_RESET_SECONDS", 1.1)

    async with httpx.AsyncClient(base_url=get_app_base_url(), timeout=15.0) as client:
        token = await get_admin_access_token(client)
        websocket_url = f"{get_websocket_url()}?token={token}"

        async with websockets.connect(websocket_url, close_timeout=5, open_timeout=10) as websocket:
            for _ in range(burst_messages):
                await websocket.send(json.dumps({"type": "ping"}))

            responses = []
            for _ in range(burst_messages):
                responses.append(json.loads(await asyncio.wait_for(websocket.recv(), timeout=5.0)))

            assert any(
                response.get("type") == "error" and "Rate limit exceeded" in response.get("message", "")
                for response in responses
            )

            await asyncio.sleep(post_burst_reset_seconds)
            await websocket.send(json.dumps({"type": "ping"}))
            recovered = json.loads(await asyncio.wait_for(websocket.recv(), timeout=5.0))

    assert recovered["type"] == "pong"
