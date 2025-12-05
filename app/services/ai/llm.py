"""LLM Client Interface and Implementations."""

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Type, TypeVar

import httpx
from pydantic import BaseModel

from app.core.circuit_breaker import get_llm_circuit_breaker
from app.core.config import settings
from app.core.exceptions import LLMConnectionError, LLMResponseError, LLMTimeoutError
from app.core.telemetry import record_llm_call, telemetry

logger = logging.getLogger("spectra.services.ai.llm")


# --- Response Types ---


@dataclass
class LLMResponse:
    """Standard response from an LLM."""

    content: str
    model: str
    provider: str
    usage: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


T = TypeVar("T", bound=BaseModel)


# --- Abstract Base Client ---


class LLMClient(ABC):
    """Abstract base class for LLM clients."""

    provider: str = "base"

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float | None = None,
    ) -> LLMResponse:
        """
        Generate a text response from the LLM.

        Args:
            prompt: The user prompt.
            system_prompt: Optional system instructions.
            temperature: Sampling temperature (0.0 - 1.0).
            max_tokens: Maximum tokens to generate.
            timeout: Request timeout in seconds.

        Returns:
            LLMResponse containing the generated text.
        """

    async def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        system_prompt: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        timeout: float | None = None,
    ) -> T:
        """
        Generate a structured response that conforms to a Pydantic model.

        Args:
            prompt: The user prompt.
            response_model: Pydantic model class for response validation.
            system_prompt: Optional system instructions.
            temperature: Sampling temperature (lower = more deterministic).
            max_tokens: Maximum tokens to generate.
            timeout: Request timeout in seconds.

        Returns:
            Validated Pydantic model instance.

        Raises:
            ValueError: If the response cannot be parsed into the model.
        """
        # Build schema-aware system prompt
        schema = response_model.model_json_schema()
        schema_prompt = f"""You must respond with valid JSON that matches this schema:
{json.dumps(schema, indent=2)}

Respond ONLY with the JSON object. No markdown, no explanation, just the JSON."""

        full_system = (
            f"{system_prompt}\n\n{schema_prompt}" if system_prompt else schema_prompt
        )

        response = await self.generate(
            prompt=prompt,
            system_prompt=full_system,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

        # Parse and validate
        try:
            # Handle potential markdown code blocks or text before/after JSON
            content = response.content.strip()

            # Find the first '{' and last '}'
            start_idx = content.find("{")
            end_idx = content.rfind("}")

            if start_idx != -1 and end_idx != -1:
                content = content[start_idx : end_idx + 1]

            # Try standard JSON parsing first
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                # Try to repair malformed JSON from LLM
                try:
                    from json_repair import repair_json

                    repaired = repair_json(content, return_objects=True)
                    if isinstance(repaired, dict):
                        data = repaired
                        logger.info("Repaired malformed JSON from LLM")
                    else:
                        raise ValueError("Repaired JSON is not a dict")
                except ImportError:
                    raise
                except Exception as repair_error:
                    logger.debug("JSON repair failed: %s", repair_error)
                    raise

            return response_model.model_validate(data)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse LLM response as JSON: %s", e)
            # Sanitize log injection
            safe_content = response.content.encode("unicode_escape").decode("utf-8")
            if len(safe_content) > 1000:
                safe_content = safe_content[:1000] + "..."
            logger.debug("Raw response: %s", safe_content)
            raise ValueError(f"LLM response is not valid JSON: {e}") from e
        except Exception as e:
            logger.error("Failed to validate LLM response: %s", e)
            raise ValueError(f"LLM response failed validation: {e}") from e

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the LLM service is available."""
        ...

    async def close(self) -> None:
        """Close any open resources (e.g., HTTP clients)."""
        pass


# --- Ollama Client ---


class OllamaClient(LLMClient):
    """Client for Ollama (local LLM inference)."""

    provider = "ollama"

    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "qwen2.5:3b",
    ):
        self.host = host.rstrip("/")
        self.model = model
        self._http_client: Any = None

    async def _get_client(self):
        """Get or create HTTP client."""
        if self._http_client is None:
            import httpx

            # Increased timeout for local LLMs which can be slow
            self._http_client = httpx.AsyncClient(timeout=settings.LLM_TIMEOUT)
        return self._http_client

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float | None = None,
    ) -> LLMResponse:
        """Generate text using Ollama API with circuit breaker and telemetry."""
        circuit_breaker = get_llm_circuit_breaker()
        start_time = time.time()
        success = False
        tokens = 0

        try:
            async with circuit_breaker:
                client = await self._get_client()

                payload = {
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens,
                    },
                }

                if system_prompt:
                    payload["system"] = system_prompt

                response = await client.post(
                    f"{self.host}/api/generate",
                    json=payload,
                    timeout=timeout,
                )
                response.raise_for_status()
                data = response.json()

                tokens = data.get("prompt_eval_count", 0) + data.get("eval_count", 0)
                success = True

                return LLMResponse(
                    content=data.get("response", ""),
                    model=self.model,
                    provider=self.provider,
                    usage={
                        "prompt_tokens": data.get("prompt_eval_count", 0),
                        "completion_tokens": data.get("eval_count", 0),
                        "total_tokens": tokens,
                    },
                    raw=data,
                )
        except httpx.TimeoutException as e:
            logger.error("Ollama request timed out: %s", e)
            raise LLMTimeoutError(
                f"Ollama request timed out: {e}", timeout=settings.LLM_TIMEOUT
            ) from e
        except httpx.HTTPStatusError as e:
            logger.error("Ollama HTTP error %d: %s", e.response.status_code, e)
            raise LLMResponseError(
                f"Ollama HTTP error: {e.response.status_code}",
                status_code=e.response.status_code,
            ) from e
        except httpx.RequestError as e:
            logger.error("Ollama connection error: %s", e)
            raise LLMConnectionError(f"Ollama connection failed: {e}", host=self.host) from e
        finally:
            # Record telemetry (fire and forget)
            duration_ms = (time.time() - start_time) * 1000
            import asyncio

            asyncio.create_task(
                record_llm_call(
                    provider=self.provider,
                    model=self.model,
                    duration_ms=duration_ms,
                    tokens=tokens,
                    success=success,
                )
            )

        # This line is unreachable but satisfies the type checker
        raise RuntimeError("Unexpected code path in generate()")

    async def health_check(self) -> bool:
        """Check if Ollama is available."""
        start_time = time.time()
        try:
            client = await self._get_client()
            response = await client.get(f"{self.host}/api/tags")
            healthy = response.status_code == 200
            latency_ms = (time.time() - start_time) * 1000
            telemetry.update_service_status("ollama", healthy=healthy, latency_ms=latency_ms)
            return healthy
        except (httpx.RequestError, httpx.TimeoutException) as e:
            logger.debug("Ollama health check failed: %s", e)
            telemetry.update_service_status("ollama", healthy=False, error=str(e))
            return False

    async def close(self):
        """Close the HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None


# --- OpenAI-Compatible API Client ---


class APIClient(LLMClient):
    """Client for OpenAI-compatible APIs (OpenAI, OpenRouter, vLLM, LocalAI, etc.)."""

    provider = "api"

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: str | None = None,
    ):
        self.model = model
        self._client: Any = None
        self._api_key = api_key
        self._base_url = base_url

    def _get_client(self):
        """Get or create OpenAI-compatible client."""
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
            )
        return self._client

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float | None = None,
    ) -> LLMResponse:
        """Generate text using OpenAI-compatible API."""
        client = self._get_client()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )

            choice = response.choices[0]
            usage = response.usage

            return LLMResponse(
                content=choice.message.content or "",
                model=self.model,
                provider=self.provider,
                usage={
                    "prompt_tokens": usage.prompt_tokens if usage else 0,
                    "completion_tokens": usage.completion_tokens if usage else 0,
                    "total_tokens": usage.total_tokens if usage else 0,
                },
                raw=response.model_dump(),
            )
        except Exception as e:
            logger.error("API generation failed: %s", e)
            raise

    async def health_check(self) -> bool:
        """Check if API is available."""
        try:
            client = self._get_client()
            await client.models.list()
            return True
        except Exception:
            return False


# Legacy alias for backwards compatibility
OpenAIClient = APIClient


# --- Mock Client (for testing) ---


class MockLLMClient(LLMClient):
    """Mock LLM client for deterministic testing."""

    provider = "mock"

    def __init__(
        self,
        responses: list[str] | None = None,
        structured_responses: dict[str, Any] | None = None,
    ):
        """
        Initialize mock client.

        Args:
            responses: List of text responses to return in order.
            structured_responses: Dict mapping Pydantic model names to response data.
        """
        self.responses = responses or ["Mock response"]
        self.structured_responses = structured_responses or {}
        self._call_count = 0
        self.call_history: list[dict[str, Any]] = []

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float | None = None,
    ) -> LLMResponse:
        """Return mock response."""
        self.call_history.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "timeout": timeout,
            }
        )

        response_idx = self._call_count % len(self.responses)
        self._call_count += 1

        return LLMResponse(
            content=self.responses[response_idx],
            model="mock-model",
            provider=self.provider,
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            raw={},
        )

    async def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        system_prompt: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        timeout: float | None = None,
    ) -> T:
        """Return mock structured response."""
        self.call_history.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "response_model": response_model.__name__,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "timeout": timeout,
            }
        )

        model_name = response_model.__name__
        if model_name in self.structured_responses:
            return response_model.model_validate(self.structured_responses[model_name])

        # Generate default response from schema
        return self._generate_default(response_model)

    def _generate_default(self, response_model: Type[T]) -> T:
        """Generate a default instance of a Pydantic model."""
        schema = response_model.model_json_schema()
        props = schema.get("properties", {})

        data = {}
        for prop_name, prop_info in props.items():
            prop_type = prop_info.get("type", "string")
            if prop_type == "string":
                data[prop_name] = f"mock_{prop_name}"
            elif prop_type == "integer":
                data[prop_name] = 0
            elif prop_type == "number":
                data[prop_name] = 0.0
            elif prop_type == "boolean":
                data[prop_name] = False
            elif prop_type == "array":
                data[prop_name] = []
            elif prop_type == "object":
                data[prop_name] = {}
            else:
                data[prop_name] = None

        return response_model.model_validate(data)

    async def health_check(self) -> bool:
        """Always returns True for mock client."""
        return True

    def reset(self):
        """Reset call count and history."""
        self._call_count = 0
        self.call_history = []


# --- Factory Function ---


def get_llm_client(
    provider: str = "ollama",
    **kwargs,
) -> LLMClient:
    """
    Factory function to get the appropriate LLM client.

    Args:
        provider: One of "ollama", "api", "openai" (legacy), or "mock".
        **kwargs: Provider-specific arguments.

    Returns:
        Configured LLM client instance.
    """
    if provider == "ollama":
        return OllamaClient(
            host=kwargs.get("host", "http://localhost:11434"),
            model=kwargs.get("model", "qwen2.5:3b"),
        )
    elif provider in ("api", "openai"):  # Support both new and legacy names
        api_key = kwargs.get("api_key")
        if not api_key:
            raise ValueError("API key is required for cloud provider")
        return APIClient(
            api_key=api_key,
            model=kwargs.get("model", "gpt-4o-mini"),
            base_url=kwargs.get("base_url"),
        )
    elif provider == "mock":
        return MockLLMClient(
            responses=kwargs.get("responses"),
            structured_responses=kwargs.get("structured_responses"),
        )
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")


def get_default_llm_client() -> LLMClient:
    """
    Get the LLM client configured in settings.

    Returns:
        LLMClient instance based on app configuration.
    """
    provider = settings.AI_PROVIDER

    if provider == "ollama":
        # For Ollama, we strictly use OLLAMA_HOST and OLLAMA_MODEL
        # ignoring any LLM_* settings which are for the API provider
        return get_llm_client(
            provider="ollama",
            host=settings.OLLAMA_HOST,
            model=settings.OLLAMA_MODEL,
        )
    elif provider in ("api", "openai"):  # Support both
        # For API, we strictly use LLM_* settings
        return get_llm_client(
            provider="api",
            api_key=settings.LLM_API_KEY.get_secret_value(),
            base_url=settings.LLM_API_BASE_URL,
            model=settings.LLM_MODEL,
        )
    elif provider == "mock":
        return get_llm_client(provider="mock")
    else:
        # Fallback or error
        logger.warning("Unknown provider %s, falling back to mock", provider)
        return get_llm_client(provider="mock")


# Global singleton
_global_llm_client: LLMClient | None = None


async def get_global_llm_client() -> LLMClient:
    """Get the global LLM client instance."""
    global _global_llm_client
    if _global_llm_client is None:
        _global_llm_client = get_default_llm_client()
    return _global_llm_client


async def close_global_llm_client() -> None:
    """Close the global LLM client."""
    global _global_llm_client
    if _global_llm_client:
        await _global_llm_client.close()
        _global_llm_client = None
