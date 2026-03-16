"""Comprehensive unit tests for app.services.ai.llm module."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from app.services.ai.llm import (
    LLMResponse,
    get_default_llm_client,
    get_llm_client,
)
from tests.mocks.llm import MockLLMClient

# --- Test Models ---


class SimpleModel(BaseModel):
    name: str
    value: int


class DetailedModel(BaseModel):
    title: str
    score: float
    active: bool
    tags: list[str]
    metadata: dict[str, Any]


# ===================================================================
# MockLLMClient Tests
# ===================================================================


class TestMockLLMClient:
    """Tests for MockLLMClient."""

    @pytest.mark.asyncio
    async def test_generate_returns_default_response(self):
        client = MockLLMClient()
        result = await client.generate("Hello")
        assert isinstance(result, LLMResponse)
        assert result.content == "Mock response"
        assert result.model == "mock-model"
        assert result.provider == "mock"

    @pytest.mark.asyncio
    async def test_generate_returns_responses_in_order(self):
        responses = ["first", "second", "third"]
        client = MockLLMClient(responses=responses)

        r1 = await client.generate("a")
        r2 = await client.generate("b")
        r3 = await client.generate("c")

        assert r1.content == "first"
        assert r2.content == "second"
        assert r3.content == "third"

    @pytest.mark.asyncio
    async def test_generate_wraps_around_responses(self):
        client = MockLLMClient(responses=["alpha", "beta"])
        await client.generate("1")
        await client.generate("2")
        r3 = await client.generate("3")
        assert r3.content == "alpha"

    @pytest.mark.asyncio
    async def test_generate_usage_fields(self):
        client = MockLLMClient()
        result = await client.generate("test")
        assert result.usage == {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
        }

    @pytest.mark.asyncio
    async def test_call_history_records_calls(self):
        client = MockLLMClient()
        await client.generate("prompt1", system_prompt="sys1", temperature=0.5)
        await client.generate("prompt2", max_tokens=512, timeout=30.0)

        assert len(client.call_history) == 2

        first = client.call_history[0]
        assert first["prompt"] == "prompt1"
        assert first["system_prompt"] == "sys1"
        assert first["temperature"] == 0.5

        second = client.call_history[1]
        assert second["prompt"] == "prompt2"
        assert second["max_tokens"] == 512
        assert second["timeout"] == 30.0

    @pytest.mark.asyncio
    async def test_reset_clears_history_and_count(self):
        client = MockLLMClient(responses=["a", "b"])
        await client.generate("x")
        await client.generate("y")
        assert len(client.call_history) == 2
        assert client._call_count == 2

        client.reset()

        assert len(client.call_history) == 0
        assert client._call_count == 0
        r = await client.generate("z")
        assert r.content == "a"

    @pytest.mark.asyncio
    async def test_generate_structured_with_structured_responses(self):
        client = MockLLMClient(structured_responses={"SimpleModel": {"name": "test", "value": 42}})
        result = await client.generate_structured("prompt", SimpleModel)
        assert isinstance(result, SimpleModel)
        assert result.name == "test"
        assert result.value == 42

    @pytest.mark.asyncio
    async def test_generate_structured_records_call_history(self):
        client = MockLLMClient(structured_responses={"SimpleModel": {"name": "x", "value": 1}})
        await client.generate_structured("prompt", SimpleModel, system_prompt="sys")
        assert len(client.call_history) == 1
        entry = client.call_history[0]
        assert entry["response_model"] == "SimpleModel"
        assert entry["system_prompt"] == "sys"

    @pytest.mark.asyncio
    async def test_generate_default_string_field(self):
        client = MockLLMClient()
        result = client._generate_default(SimpleModel)
        assert isinstance(result, SimpleModel)
        assert result.name == "mock_name"
        assert result.value == 0

    @pytest.mark.asyncio
    async def test_generate_default_all_types(self):
        client = MockLLMClient()
        result = client._generate_default(DetailedModel)
        assert isinstance(result, DetailedModel)
        assert result.title == "mock_title"
        assert result.score == 0.0
        assert result.active is False
        assert result.tags == []
        assert result.metadata == {}

    @pytest.mark.asyncio
    async def test_generate_structured_falls_back_to_default(self):
        client = MockLLMClient()
        result = await client.generate_structured("prompt", SimpleModel)
        assert isinstance(result, SimpleModel)
        assert result.name == "mock_name"
        assert result.value == 0

    @pytest.mark.asyncio
    async def test_health_check_returns_true(self):
        client = MockLLMClient()
        assert await client.health_check() is True


# ===================================================================
# generate_structured (LLMClient base class) Tests
# ===================================================================


class TestGenerateStructured:
    """Tests for the base LLMClient.generate_structured JSON parsing logic."""

    @pytest.mark.asyncio
    async def test_parse_clean_json(self):
        raw_json = json.dumps({"name": "hello", "value": 10})
        client = MockLLMClient(responses=[raw_json])
        # Use the base class generate_structured (not the mock override)
        result = await _call_base_generate_structured(client, "prompt", SimpleModel)
        assert result.name == "hello"
        assert result.value == 10

    @pytest.mark.asyncio
    async def test_parse_json_in_markdown_code_block(self):
        content = '```json\n{"name": "block", "value": 99}\n```'
        client = MockLLMClient(responses=[content])
        result = await _call_base_generate_structured(client, "prompt", SimpleModel)
        assert result.name == "block"
        assert result.value == 99

    @pytest.mark.asyncio
    async def test_parse_json_with_surrounding_text(self):
        content = 'Here is the result: {"name": "embedded", "value": 7} hope that helps!'
        client = MockLLMClient(responses=[content])
        result = await _call_base_generate_structured(client, "prompt", SimpleModel)
        assert result.name == "embedded"
        assert result.value == 7

    @pytest.mark.asyncio
    async def test_json_repair_fallback(self):
        malformed = '{"name": "broken", "value": 5,}'
        client = MockLLMClient(responses=[malformed])
        result = await _call_base_generate_structured(client, "prompt", SimpleModel)
        assert result.name == "broken"
        assert result.value == 5

    @pytest.mark.asyncio
    async def test_validation_error_raises_value_error(self):
        wrong_types = json.dumps({"name": 123, "value": "not_an_int"})
        client = MockLLMClient(responses=[wrong_types])
        with pytest.raises(ValueError, match="validation"):
            await _call_base_generate_structured(client, "prompt", SimpleModel)

    @pytest.mark.asyncio
    async def test_no_json_at_all_raises_value_error(self):
        client = MockLLMClient(responses=["no json here at all"])
        with pytest.raises(ValueError):
            await _call_base_generate_structured(client, "prompt", SimpleModel)

    @pytest.mark.asyncio
    async def test_system_prompt_includes_schema(self):
        raw_json = json.dumps({"name": "x", "value": 1})
        client = MockLLMClient(responses=[raw_json])
        await _call_base_generate_structured(client, "prompt", SimpleModel, system_prompt="custom sys")
        call = client.call_history[0]
        assert "custom sys" in call["system_prompt"]
        assert "JSON" in call["system_prompt"]


# ===================================================================
# get_llm_client Factory Tests
# ===================================================================


class TestGetLLMClient:
    """Tests for the get_llm_client factory function."""

    def test_ollama_provider_returns_litellm_router(self):
        from app.services.ai.router import LiteLLMRouter

        client = get_llm_client("ollama", host="http://myhost:1234", model="mymodel")
        assert isinstance(client, LiteLLMRouter)

    def test_litellm_provider(self):
        from app.services.ai.router import LiteLLMRouter

        client = get_llm_client("litellm", model="gpt-4", api_key="sk-test")
        assert isinstance(client, LiteLLMRouter)

    def test_api_provider_returns_litellm_router(self):
        from app.services.ai.router import LiteLLMRouter

        client = get_llm_client("api", api_key="sk-test", model="gpt-4")
        assert isinstance(client, LiteLLMRouter)

    def test_openai_legacy_alias(self):
        from app.services.ai.router import LiteLLMRouter

        client = get_llm_client("openai", api_key="sk-test")
        assert isinstance(client, LiteLLMRouter)

    def test_mock_provider_raises(self):
        with pytest.raises(ValueError, match="Unsupported LLM provider"):
            get_llm_client("mock")


# ===================================================================
# get_default_llm_client Tests
# ===================================================================


class TestGetDefaultLLMClient:
    """Tests for get_default_llm_client reading from settings."""

    def test_ollama_provider(self):
        mock_settings = MagicMock()
        mock_settings.AI_PROVIDER = "ollama"
        mock_settings.OLLAMA_HOST = "http://ollama:11434"
        mock_settings.OLLAMA_MODEL = "llama3"
        mock_settings.LLM_API_KEY = MagicMock()
        mock_settings.LLM_API_KEY.get_secret_value.return_value = ""
        mock_settings.LLM_API_BASE_URL = None
        mock_settings.LLM_MODEL = None
        mock_settings.LLM_TIMEOUT = 600.0

        with (
            patch("app.services.ai.llm.settings", mock_settings),
            patch("app.services.ai.router.settings", mock_settings),
        ):
            client = get_default_llm_client()
            from app.services.ai.router import LiteLLMRouter

            assert isinstance(client, LiteLLMRouter)

    def test_api_provider(self):
        mock_settings = MagicMock()
        mock_settings.AI_PROVIDER = "api"
        mock_settings.LLM_API_KEY = MagicMock()
        mock_settings.LLM_API_KEY.get_secret_value.return_value = "sk-secret"
        mock_settings.LLM_API_BASE_URL = "https://api.example.com"
        mock_settings.LLM_MODEL = "gpt-4o"
        mock_settings.LLM_TIMEOUT = 600.0

        with (
            patch("app.services.ai.llm.settings", mock_settings),
            patch("app.services.ai.router.settings", mock_settings),
        ):
            client = get_default_llm_client()
            from app.services.ai.router import LiteLLMRouter

            assert isinstance(client, LiteLLMRouter)

    def test_openai_legacy_provider(self):
        mock_settings = MagicMock()
        mock_settings.AI_PROVIDER = "openai"
        mock_settings.LLM_API_KEY = MagicMock()
        mock_settings.LLM_API_KEY.get_secret_value.return_value = "sk-legacy"
        mock_settings.LLM_API_BASE_URL = None
        mock_settings.LLM_MODEL = "gpt-3.5-turbo"
        mock_settings.LLM_TIMEOUT = 600.0

        with (
            patch("app.services.ai.llm.settings", mock_settings),
            patch("app.services.ai.router.settings", mock_settings),
        ):
            client = get_default_llm_client()
            from app.services.ai.router import LiteLLMRouter

            assert isinstance(client, LiteLLMRouter)

    @patch("app.services.ai.router.settings")
    @patch("app.services.ai.llm.settings")
    def test_mock_provider_raises(self, mock_llm_settings, mock_router_settings):
        mock_llm_settings.AI_PROVIDER = "mock"
        mock_router_settings.AI_PROVIDER = "mock"
        with pytest.raises(ValueError, match="Unsupported LLM provider"):
            get_default_llm_client()

    @patch("app.services.ai.router.settings")
    @patch("app.services.ai.llm.settings")
    def test_unknown_provider_returns_litellm(self, mock_llm_settings, mock_router_settings):
        """Unknown providers now normalize to litellm instead of raising."""
        mock_llm_settings.AI_PROVIDER = "unknown_provider"
        mock_router_settings.AI_PROVIDER = "unknown_provider"
        mock_router_settings.LLM_API_KEY = MagicMock()
        mock_router_settings.LLM_API_KEY.get_secret_value.return_value = ""
        mock_router_settings.LLM_API_BASE_URL = None
        mock_router_settings.LLM_MODEL = "test-model"
        mock_router_settings.LLM_TIMEOUT = 600.0
        mock_router_settings.OLLAMA_HOST = "http://ai:11434"
        mock_router_settings.OLLAMA_MODEL = "qwen2.5:3b"
        mock_llm_settings.LLM_MODEL = "test-model"
        from app.services.ai.router import LiteLLMRouter

        client = get_default_llm_client()
        assert isinstance(client, LiteLLMRouter)


# ===================================================================
# LLMResponse Dataclass Tests
# ===================================================================


class TestLLMResponse:
    """Tests for the LLMResponse dataclass."""

    def test_basic_creation(self):
        r = LLMResponse(content="hi", model="m", provider="p")
        assert r.content == "hi"
        assert r.model == "m"
        assert r.provider == "p"
        assert r.usage == {}
        assert r.raw == {}

    def test_full_creation(self):
        r = LLMResponse(
            content="c",
            model="m",
            provider="p",
            usage={"total_tokens": 10},
            raw={"id": "x"},
        )
        assert r.usage == {"total_tokens": 10}
        assert r.raw == {"id": "x"}


# ===================================================================
# Helpers
# ===================================================================


class _NoopCircuitBreaker:
    """A trivial async context manager that does nothing."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _noop_circuit_breaker():
    return _NoopCircuitBreaker()


async def _call_base_generate_structured(
    client: MockLLMClient,
    prompt: str,
    response_model,
    system_prompt: str | None = None,
):
    """Call the base LLMClient.generate_structured instead of the mock override."""
    from app.services.ai.llm import LLMClient

    return await LLMClient.generate_structured(
        client,
        prompt=prompt,
        response_model=response_model,
        system_prompt=system_prompt,
    )
