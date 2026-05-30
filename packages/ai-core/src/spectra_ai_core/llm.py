"""Abstract LLM client interface, response types, and global singleton management."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)


def get_ai_settings():
    """Return AI settings. Override via register_settings_factory or this is a no-op stub."""
    if _settings_factory is not None:
        return _settings_factory()
    import os
    from types import SimpleNamespace
    return SimpleNamespace(
        TENSORZERO_GATEWAY_URL=os.environ.get("TENSORZERO_GATEWAY_URL", ""),
        LLM_TIMEOUT=float(os.environ.get("LLM_TIMEOUT", "600")),
    )


_settings_factory = None


def register_settings_factory(factory) -> None:
    """Register a callable that returns AI settings. Called by services/ai at startup."""
    global _settings_factory
    _settings_factory = factory


def _extract_json_block(text: str) -> str:
    """Extract first complete JSON object from text using brace depth tracking."""
    start = text.find("{")
    if start == -1:
        return text
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(text[start:], start):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start : text.rfind("}") + 1]


@dataclass
class LLMResponse:
    """Standard response from an LLM."""

    content: str
    model: str
    provider: str
    usage: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


T = TypeVar("T", bound=BaseModel)


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
    ) -> LLMResponse:
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
            except (OSError, RuntimeError, ValueError, TimeoutError) as e:
                last_error = e
                if attempt < self.MAX_RETRIES - 1:
                    delay = min(2**attempt + random.uniform(0, 1), 30)
                    logger.warning(
                        "LLM call failed (attempt %d/%d): %s. Retrying in %.1fs...",
                        attempt + 1,
                        self.MAX_RETRIES,
                        e,
                        delay,
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
        """Generate a text response from the LLM."""

    async def stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float | None = None,
        task_type: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream tokens from the LLM. Default falls back to non-streaming generate()."""
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
        """Generate a structured response that conforms to a Pydantic model."""
        schema = response_model.model_json_schema()
        schema_prompt = f"""You must respond with valid JSON that matches this schema:
{json.dumps(schema, indent=2)}

Respond ONLY with the JSON object. No markdown, no explanation, just the JSON."""

        full_system = f"{system_prompt}\n\n{schema_prompt}" if system_prompt else schema_prompt

        response = await self.generate(
            prompt=prompt,
            system_prompt=full_system,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            task_type=task_type,
        )

        try:
            content = response.content.strip()
            start_idx = content.find("{")
            if start_idx != -1:
                content = _extract_json_block(content)

            try:
                data = json.loads(content)
            except json.JSONDecodeError:
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
                except (ValueError, TypeError, KeyError) as repair_error:
                    logger.debug("JSON repair failed: %s", repair_error)
                    raise

            return response_model.model_validate(data)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse LLM response as JSON: %s", e)
            safe_content = response.content.encode("unicode_escape").decode("utf-8")
            if len(safe_content) > 1000:
                safe_content = safe_content[:1000] + "..."
            logger.debug("Raw response: %s", safe_content)
            raise ValueError(f"LLM response is not valid JSON: {e}") from e
        except (ValueError, TypeError, KeyError) as e:
            logger.error("Failed to validate LLM response: %s", e)
            raise ValueError(f"LLM response failed validation: {e}") from e

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the LLM service is available."""
        raise NotImplementedError("Subclass must implement health_check")

    async def close(self) -> None:
        """Close any open resources."""


# ---------------------------------------------------------------------------
# Global singleton management — concrete implementation is injected by
# services/ai at startup via register_llm_factory() / set_global_llm_client().
# ---------------------------------------------------------------------------

_global_llm_client: LLMClient | None = None
_llm_factory: Any = None


def register_llm_factory(factory: Any) -> None:
    """Register a factory callable that creates LLMClient instances.

    Called once by services/ai at startup so bounded packages can call
    get_llm_client() without importing the concrete service package.
    """
    global _llm_factory
    _llm_factory = factory


def get_llm_client(provider: str = "tensorzero", **kwargs: Any) -> LLMClient:
    """Create a new LLM client via the registered factory."""
    if _llm_factory is None:
        raise RuntimeError(
            "No LLM factory registered. services/ai must call "
            "spectra_ai_core.llm.register_llm_factory() at startup."
        )
    return _llm_factory(provider=provider, **kwargs)


def get_default_llm_client() -> LLMClient:
    """Get the default LLM client configured via settings."""
    settings = get_ai_settings()
    gateway_url = getattr(settings, "TENSORZERO_GATEWAY_URL", "")
    if not gateway_url:
        raise ValueError(
            "TENSORZERO_GATEWAY_URL is not configured. "
            "Set it to the TensorZero gateway address (e.g., http://tensorzero:3000)"
        )
    return get_llm_client(gateway_url=gateway_url)


async def get_global_llm_client() -> LLMClient:
    """Get (or lazily create) the global LLM client singleton."""
    global _global_llm_client
    if _global_llm_client is None:
        _global_llm_client = get_llm_client()
    return _global_llm_client


async def close_global_llm_client() -> None:
    """Close and release the global LLM client singleton."""
    global _global_llm_client
    if _global_llm_client:
        await _global_llm_client.close()
        _global_llm_client = None
