"""Contract tests for the split-deployment LLM adapter."""

from unittest.mock import AsyncMock

import pytest

from spectra_ai_core.gateway.llm_client import GatewayLLMClient


@pytest.mark.asyncio
async def test_gateway_client_maps_messages_tier_and_response() -> None:
    gateway = AsyncMock()
    gateway.chat.return_value = {
        "content": "plan",
        "model": "test-model",
        "usage": {"prompt_tokens": 4, "completion_tokens": 2},
    }
    client = GatewayLLMClient(gateway)

    response = await client.generate(
        "make a plan",
        system_prompt="you are safe",
        temperature=0.2,
        max_tokens=128,
        task_type="planning",
    )

    assert response.content == "plan"
    assert response.provider == "ai-gateway"
    assert response.model == "test-model"
    gateway.chat.assert_awaited_once_with(
        [
            {"role": "system", "content": "you are safe"},
            {"role": "user", "content": "make a plan"},
        ],
        tier=2,
        temperature=0.2,
        max_tokens=128,
    )


@pytest.mark.asyncio
async def test_gateway_client_stream_health_and_close() -> None:
    gateway = AsyncMock()
    gateway.chat.return_value = {"content": "chunk"}
    gateway.check_llm_status.return_value = {"available": True}
    client = GatewayLLMClient(gateway)

    chunks = [chunk async for chunk in client.stream("hello", task_type="parsing")]

    assert chunks == ["chunk"]
    assert await client.health_check()
    await client.close()
    gateway.check_llm_status.assert_awaited_once_with()
    gateway.close.assert_awaited_once_with()
    assert gateway.chat.await_args.kwargs["tier"] == 1
