"""Tests for tests.mocks.llm.MockLLMClient (consolidated mock)."""

import pytest

from tests.mocks.llm import MockLLMClient


@pytest.mark.asyncio
class TestMockLLMGenerate:
    async def test_returns_llm_response(self):
        client = MockLLMClient()
        resp = await client.generate("Hello")
        assert resp.content is not None
        assert resp.model == "mock-model"
        assert resp.provider == "mock"
        assert resp.usage["total_tokens"] == 30

    async def test_default_response(self):
        client = MockLLMClient()
        resp = await client.generate("Hello")
        assert resp.content == "Mock response"

    async def test_custom_responses_cycle(self):
        client = MockLLMClient(responses=["first", "second"])
        r1 = await client.generate("a")
        r2 = await client.generate("b")
        r3 = await client.generate("c")  # wraps around
        assert r1.content == "first"
        assert r2.content == "second"
        assert r3.content == "first"

    async def test_call_history_recorded(self):
        client = MockLLMClient()
        await client.generate("test prompt", system_prompt="sys")
        assert len(client.call_history) == 1
        assert client.call_history[0]["prompt"] == "test prompt"
        assert client.call_history[0]["system_prompt"] == "sys"

    async def test_optional_params_accepted(self):
        client = MockLLMClient()
        resp = await client.generate(
            "test",
            system_prompt="You are a security expert",
            temperature=0.3,
            max_tokens=512,
            timeout=10.0,
            task_type="analysis",
        )
        assert resp.content is not None


@pytest.mark.asyncio
class TestMockLLMHealthCheck:
    async def test_health_check_returns_true(self):
        client = MockLLMClient()
        assert await client.health_check() is True


class TestMockLLMAttributes:
    def test_provider_is_mock(self):
        assert MockLLMClient.provider == "mock"
