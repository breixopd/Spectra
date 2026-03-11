"""LLM Client Interface and Implementations."""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core.config import settings

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
    MAX_RETRIES: int = 3

    async def generate_with_retry(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float | None = None,
        task_type: str | None = None,
    ) -> "LLMResponse":
        """Generate with exponential backoff retry on transient failures."""
        last_error: Exception | None = None
        for attempt in range(self.MAX_RETRIES):
            try:
                return await self.generate(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    task_type=task_type,
                )
            except Exception as e:
                last_error = e
                if attempt < self.MAX_RETRIES - 1:
                    delay = 2 ** attempt
                    logger.warning(
                        "LLM call failed (attempt %d/%d): %s. Retrying in %ds...",
                        attempt + 1, self.MAX_RETRIES, e, delay,
                    )
                    await asyncio.sleep(delay)
        raise last_error  # type: ignore[misc]

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float | None = None,
        task_type: str | None = None,
    ) -> LLMResponse:
        """
        Generate a text response from the LLM.

        Args:
            prompt: The user prompt.
            system_prompt: Optional system instructions.
            temperature: Sampling temperature (0.0 - 1.0).
            max_tokens: Maximum tokens to generate.
            timeout: Request timeout in seconds.
            task_type: Task type for model routing (e.g. 'scope', 'exploit_crafting').

        Returns:
            LLMResponse containing the generated text.
        """

    async def stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float | None = None,
        task_type: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream tokens from the LLM. Yields text chunks.

        Default implementation falls back to non-streaming generate().
        Override in subclasses that support native streaming.
        """
        response = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            task_type=task_type,
        )
        yield response.content

    async def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        system_prompt: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        timeout: float | None = None,
        task_type: str | None = None,
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
            task_type: Task type for model routing.

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
            task_type=task_type,
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


# --- Factory Function ---


def get_llm_client(
    provider: str = "litellm",
    **kwargs,
) -> LLMClient:
    """
    Factory function to get the appropriate LLM client.

    Args:
        provider: "litellm" (all providers) or "mock" (testing).
        **kwargs: Provider-specific arguments.

    Returns:
        Configured LLM client instance.
    """
    from app.services.ai.router import LiteLLMRouter, _normalize_provider_name

    normalized_provider = _normalize_provider_name(provider)

    if normalized_provider == "mock":
        try:
            from tests.mocks.llm import PentestMockLLMClient
        except ImportError:
            raise ValueError(
                "Mock provider requires test dependencies. "
                "Set AI_PROVIDER to 'litellm' for production use."
            ) from None
        return PentestMockLLMClient(
            responses=kwargs.get("responses"),
            structured_responses=kwargs.get("structured_responses"),
        )

    # Everything else goes through LiteLLM
    model = kwargs.get("model", "")
    base_url = kwargs.get("base_url") or kwargs.get("host")
    api_key = kwargs.get("api_key")

    # Detect Ollama-style requests: if host is provided or raw provider is "ollama"
    raw_lower = (provider or "").strip().lower()
    if raw_lower == "ollama" and model and not model.startswith("ollama/"):
        model = f"ollama/{model}"

    model_configs = []
    if model:
        litellm_params: dict[str, Any] = {"model": model}
        if base_url:
            litellm_params["api_base"] = base_url
        if api_key:
            litellm_params["api_key"] = api_key
        model_configs.append({"model_name": "default", "litellm_params": litellm_params})

    return LiteLLMRouter(
        model_configs=model_configs or None,
        default_model=model or "openai/gpt-4o-mini",
    )


def get_default_llm_client() -> LLMClient:
    """Get the LLM client configured in settings.

    Uses in-process LiteLLM router with provider profiles.
    """


    from app.services.ai.router import LiteLLMRouter, _normalize_provider_name, create_smart_router

    provider = _normalize_provider_name(settings.AI_PROVIDER)

    if provider == "mock":
        return get_llm_client(provider="mock")

    try:
        client = create_smart_router()
        logger.info("Using LiteLLM smart router (provider=%s)", settings.AI_PROVIDER)
        return client
    except Exception as e:
        logger.warning("Smart router init failed, falling back to direct LiteLLM: %s", e)
        return LiteLLMRouter(default_model=settings.LLM_MODEL or "openai/gpt-4o-mini")


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
