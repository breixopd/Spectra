"""Comprehensive unit tests for app.services.ai.llm module."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic import BaseModel

from app.core.exceptions import LLMConnectionError, LLMResponseError, LLMTimeoutError
from app.services.ai.llm import (
    APIClient,
    LLMResponse,
    MockLLMClient,
    OllamaClient,
    get_default_llm_client,
    get_llm_client,
)


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
        client = MockLLMClient(
            structured_responses={"SimpleModel": {"name": "test", "value": 42}}
        )
        result = await client.generate_structured("prompt", SimpleModel)
        assert isinstance(result, SimpleModel)
        assert result.name == "test"
        assert result.value == 42

    @pytest.mark.asyncio
    async def test_generate_structured_records_call_history(self):
        client = MockLLMClient(
            structured_responses={"SimpleModel": {"name": "x", "value": 1}}
        )
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
# OllamaClient Tests
# ===================================================================


class TestOllamaClient:
    """Tests for OllamaClient with mocked httpx."""

    def _make_client(self, host="http://localhost:11434", model="test-model"):
        return OllamaClient(host=host, model=model)

    @pytest.mark.asyncio
    async def test_generate_successful(self):
        client = self._make_client()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "response": "generated text",
            "prompt_eval_count": 10,
            "eval_count": 20,
        }
        mock_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        client._http_client = mock_http

        with patch("app.services.ai.llm.get_llm_circuit_breaker") as mock_cb:
            mock_cb.return_value = _noop_circuit_breaker()
            result = await client.generate("hello", system_prompt="be nice")

        assert isinstance(result, LLMResponse)
        assert result.content == "generated text"
        assert result.model == "test-model"
        assert result.provider == "ollama"
        assert result.usage["prompt_tokens"] == 10
        assert result.usage["completion_tokens"] == 20
        assert result.usage["total_tokens"] == 30

        call_kwargs = mock_http.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["system"] == "be nice"

    @pytest.mark.asyncio
    async def test_generate_timeout_error(self):
        client = self._make_client()
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        client._http_client = mock_http

        with patch("app.services.ai.llm.get_llm_circuit_breaker") as mock_cb:
            mock_cb.return_value = _noop_circuit_breaker()
            with pytest.raises(LLMTimeoutError):
                await client.generate("hello")

    @pytest.mark.asyncio
    async def test_generate_http_status_error(self):
        client = self._make_client()
        mock_response = MagicMock()
        mock_response.status_code = 500
        error = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_response
        )

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=error)
        client._http_client = mock_http

        with patch("app.services.ai.llm.get_llm_circuit_breaker") as mock_cb:
            mock_cb.return_value = _noop_circuit_breaker()
            with pytest.raises(LLMResponseError):
                await client.generate("hello")

    @pytest.mark.asyncio
    async def test_generate_connection_error(self):
        client = self._make_client()
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )
        client._http_client = mock_http

        with patch("app.services.ai.llm.get_llm_circuit_breaker") as mock_cb:
            mock_cb.return_value = _noop_circuit_breaker()
            with pytest.raises(LLMConnectionError):
                await client.generate("hello")

    @pytest.mark.asyncio
    async def test_health_check_healthy(self):
        client = self._make_client()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_response)
        client._http_client = mock_http

        with patch("app.services.ai.llm.telemetry") as mock_tel:
            result = await client.health_check()

        assert result is True
        mock_tel.update_service_status.assert_called_once()
        call_kwargs = mock_tel.update_service_status.call_args
        assert call_kwargs[0][0] == "ollama"
        assert call_kwargs[1]["healthy"] is True

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self):
        client = self._make_client()
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        client._http_client = mock_http

        with patch("app.services.ai.llm.telemetry") as mock_tel:
            result = await client.health_check()

        assert result is False
        mock_tel.update_service_status.assert_called_once()
        call_kwargs = mock_tel.update_service_status.call_args
        assert call_kwargs[0][0] == "ollama"
        assert call_kwargs[1]["healthy"] is False

    @pytest.mark.asyncio
    async def test_health_check_non_200(self):
        client = self._make_client()
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_response)
        client._http_client = mock_http

        with patch("app.services.ai.llm.telemetry"):
            result = await client.health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_close_closes_client(self):
        client = self._make_client()
        mock_http = AsyncMock()
        client._http_client = mock_http
        await client.close()
        mock_http.aclose.assert_awaited_once()
        assert client._http_client is None

    @pytest.mark.asyncio
    async def test_close_noop_when_no_client(self):
        client = self._make_client()
        await client.close()

    @pytest.mark.asyncio
    async def test_host_trailing_slash_stripped(self):
        client = OllamaClient(host="http://localhost:11434/")
        assert client.host == "http://localhost:11434"


# ===================================================================
# APIClient Tests
# ===================================================================


class TestAPIClient:
    """Tests for APIClient with mocked openai."""

    def _make_client(self, api_key="test-key", model="gpt-test", base_url=None):
        return APIClient(api_key=api_key, model=model, base_url=base_url)

    @pytest.mark.asyncio
    async def test_generate_successful(self):
        client = self._make_client()

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 5
        mock_usage.completion_tokens = 15
        mock_usage.total_tokens = 20

        mock_message = MagicMock()
        mock_message.content = "API response text"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_completion = MagicMock()
        mock_completion.choices = [mock_choice]
        mock_completion.usage = mock_usage
        mock_completion.model_dump.return_value = {"id": "test"}

        mock_openai_client = AsyncMock()
        mock_openai_client.chat.completions.create = AsyncMock(
            return_value=mock_completion
        )
        client._client = mock_openai_client

        result = await client.generate("prompt", system_prompt="system")

        assert isinstance(result, LLMResponse)
        assert result.content == "API response text"
        assert result.model == "gpt-test"
        assert result.provider == "api"
        assert result.usage["prompt_tokens"] == 5
        assert result.usage["completion_tokens"] == 15
        assert result.usage["total_tokens"] == 20

    @pytest.mark.asyncio
    async def test_generate_with_system_prompt_messages(self):
        client = self._make_client()

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 1
        mock_usage.completion_tokens = 1
        mock_usage.total_tokens = 2

        mock_message = MagicMock()
        mock_message.content = "ok"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_completion = MagicMock()
        mock_completion.choices = [mock_choice]
        mock_completion.usage = mock_usage
        mock_completion.model_dump.return_value = {}

        mock_openai_client = AsyncMock()
        mock_openai_client.chat.completions.create = AsyncMock(
            return_value=mock_completion
        )
        client._client = mock_openai_client

        await client.generate("user msg", system_prompt="sys msg")

        call_kwargs = mock_openai_client.chat.completions.create.call_args[1]
        messages = call_kwargs["messages"]
        assert len(messages) == 2
        assert messages[0] == {"role": "system", "content": "sys msg"}
        assert messages[1] == {"role": "user", "content": "user msg"}

    @pytest.mark.asyncio
    async def test_generate_without_system_prompt(self):
        client = self._make_client()

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 1
        mock_usage.completion_tokens = 1
        mock_usage.total_tokens = 2

        mock_message = MagicMock()
        mock_message.content = "ok"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_completion = MagicMock()
        mock_completion.choices = [mock_choice]
        mock_completion.usage = mock_usage
        mock_completion.model_dump.return_value = {}

        mock_openai_client = AsyncMock()
        mock_openai_client.chat.completions.create = AsyncMock(
            return_value=mock_completion
        )
        client._client = mock_openai_client

        await client.generate("user msg")

        call_kwargs = mock_openai_client.chat.completions.create.call_args[1]
        messages = call_kwargs["messages"]
        assert len(messages) == 1
        assert messages[0] == {"role": "user", "content": "user msg"}

    @pytest.mark.asyncio
    async def test_generate_none_content_returns_empty(self):
        client = self._make_client()

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 0
        mock_usage.completion_tokens = 0
        mock_usage.total_tokens = 0

        mock_message = MagicMock()
        mock_message.content = None

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_completion = MagicMock()
        mock_completion.choices = [mock_choice]
        mock_completion.usage = mock_usage
        mock_completion.model_dump.return_value = {}

        mock_openai_client = AsyncMock()
        mock_openai_client.chat.completions.create = AsyncMock(
            return_value=mock_completion
        )
        client._client = mock_openai_client

        result = await client.generate("prompt")
        assert result.content == ""

    @pytest.mark.asyncio
    async def test_generate_no_usage(self):
        client = self._make_client()

        mock_message = MagicMock()
        mock_message.content = "ok"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_completion = MagicMock()
        mock_completion.choices = [mock_choice]
        mock_completion.usage = None
        mock_completion.model_dump.return_value = {}

        mock_openai_client = AsyncMock()
        mock_openai_client.chat.completions.create = AsyncMock(
            return_value=mock_completion
        )
        client._client = mock_openai_client

        result = await client.generate("prompt")
        assert result.usage["prompt_tokens"] == 0
        assert result.usage["completion_tokens"] == 0
        assert result.usage["total_tokens"] == 0

    @pytest.mark.asyncio
    async def test_generate_exception_propagates(self):
        client = self._make_client()

        mock_openai_client = AsyncMock()
        mock_openai_client.chat.completions.create = AsyncMock(
            side_effect=Exception("API error")
        )
        client._client = mock_openai_client

        with pytest.raises(Exception, match="API error"):
            await client.generate("prompt")

    @pytest.mark.asyncio
    async def test_health_check_healthy(self):
        client = self._make_client()

        mock_openai_client = AsyncMock()
        mock_openai_client.models.list = AsyncMock(return_value=[])
        client._client = mock_openai_client

        assert await client.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self):
        client = self._make_client()

        mock_openai_client = AsyncMock()
        mock_openai_client.models.list = AsyncMock(
            side_effect=Exception("auth error")
        )
        client._client = mock_openai_client

        assert await client.health_check() is False


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
        await _call_base_generate_structured(
            client, "prompt", SimpleModel, system_prompt="custom sys"
        )
        call = client.call_history[0]
        assert "custom sys" in call["system_prompt"]
        assert "JSON" in call["system_prompt"]


# ===================================================================
# get_llm_client Factory Tests
# ===================================================================


class TestGetLLMClient:
    """Tests for the get_llm_client factory function."""

    def test_ollama_provider(self):
        client = get_llm_client("ollama", host="http://myhost:1234", model="mymodel")
        assert isinstance(client, OllamaClient)
        assert client.host == "http://myhost:1234"
        assert client.model == "mymodel"

    def test_ollama_defaults(self):
        client = get_llm_client("ollama")
        assert isinstance(client, OllamaClient)
        assert client.host == "http://localhost:11434"
        assert client.model == "qwen2.5:3b"

    def test_api_provider(self):
        client = get_llm_client("api", api_key="sk-test", model="gpt-4")
        assert isinstance(client, APIClient)
        assert client.model == "gpt-4"

    def test_openai_legacy_alias(self):
        client = get_llm_client("openai", api_key="sk-test")
        assert isinstance(client, APIClient)

    def test_api_without_key_raises(self):
        with pytest.raises(ValueError, match="API key is required"):
            get_llm_client("api")

    def test_mock_provider(self):
        client = get_llm_client("mock", responses=["hi"])
        assert isinstance(client, MockLLMClient)
        assert client.responses == ["hi"]

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_llm_client("nonexistent")


# ===================================================================
# get_default_llm_client Tests
# ===================================================================


class TestGetDefaultLLMClient:
    """Tests for get_default_llm_client reading from settings."""

    @patch("app.services.ai.llm.settings")
    def test_ollama_provider(self, mock_settings):
        mock_settings.AI_PROVIDER = "ollama"
        mock_settings.OLLAMA_HOST = "http://ollama:11434"
        mock_settings.OLLAMA_MODEL = "llama3"

        client = get_default_llm_client()
        assert isinstance(client, OllamaClient)
        assert client.host == "http://ollama:11434"
        assert client.model == "llama3"

    @patch("app.services.ai.llm.settings")
    def test_api_provider(self, mock_settings):
        mock_settings.AI_PROVIDER = "api"
        mock_secret = MagicMock()
        mock_secret.get_secret_value.return_value = "sk-secret"
        mock_settings.LLM_API_KEY = mock_secret
        mock_settings.LLM_API_BASE_URL = "https://api.example.com"
        mock_settings.LLM_MODEL = "gpt-4o"

        client = get_default_llm_client()
        assert isinstance(client, APIClient)
        assert client.model == "gpt-4o"

    @patch("app.services.ai.llm.settings")
    def test_openai_legacy_provider(self, mock_settings):
        mock_settings.AI_PROVIDER = "openai"
        mock_secret = MagicMock()
        mock_secret.get_secret_value.return_value = "sk-legacy"
        mock_settings.LLM_API_KEY = mock_secret
        mock_settings.LLM_API_BASE_URL = None
        mock_settings.LLM_MODEL = "gpt-3.5-turbo"

        client = get_default_llm_client()
        assert isinstance(client, APIClient)

    @patch("app.services.ai.llm.settings")
    def test_mock_provider(self, mock_settings):
        mock_settings.AI_PROVIDER = "mock"
        client = get_default_llm_client()
        assert isinstance(client, MockLLMClient)

    @patch("app.services.ai.llm.settings")
    def test_unknown_provider_falls_back_to_mock(self, mock_settings):
        mock_settings.AI_PROVIDER = "unknown_provider"
        client = get_default_llm_client()
        assert isinstance(client, MockLLMClient)


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
