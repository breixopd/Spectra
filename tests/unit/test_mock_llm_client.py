"""Tests for tests.mocks.mock_llm_client.MockLLMClient."""

import json

import pytest

from tests.mocks.mock_llm_client import MockLLMClient


@pytest.mark.asyncio
class TestMockLLMGenerate:
    async def test_returns_llm_response(self):
        client = MockLLMClient()
        resp = await client.generate("Hello")
        assert resp.content is not None
        assert resp.model == "mock"
        assert resp.provider == "mock"
        assert resp.usage["total_tokens"] == 10

    async def test_response_is_valid_json(self):
        client = MockLLMClient()
        resp = await client.generate("Hello")
        parsed = json.loads(resp.content)
        assert "status" in parsed or "result" in parsed

    async def test_json_prompt_returns_json_response(self):
        client = MockLLMClient()
        resp = await client.generate("Return JSON data for analysis")
        parsed = json.loads(resp.content)
        assert parsed["result"] == "mock_response"
        assert parsed["confidence"] == 0.5

    async def test_non_json_prompt_returns_default(self):
        client = MockLLMClient()
        resp = await client.generate("Explain the vulnerability")
        parsed = json.loads(resp.content)
        assert parsed["status"] == "mock"

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
