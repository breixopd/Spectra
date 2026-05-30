"""
TensorZero-Powered Smart Router for LLM Requests.

Routes all LLM requests through the TensorZero gateway, which provides:
- Unified multi-provider API (OpenAI, Anthropic, Ollama, etc.)
- Automatic fallbacks between providers
- A/B testing and prompt experimentation
- Inference observability and cost tracking
- Task-function mapping for per-task model routing

Usage:
    router = get_smart_router()
    response = await router.generate("What ports are open?", task_type="tool_selection")
"""

import logging
import time
from collections.abc import AsyncIterator
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from spectra_ai.settings import get_ai_settings
from spectra_ai_core.llm import LLMClient, LLMResponse
from spectra_ai_core.telemetry_hooks import record_llm_call

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Task → model tier. Each task is also a TensorZero function name (config/tensorzero.toml),
# whose `default` variant points at one of these tiers. This map is the in-code mirror of
# that function→tier assignment and is the single source of truth for cost/observability
# attribution; `tests/unit/services/test_tensorzero_config.py` asserts it stays in sync with
# the gateway TOML so the two can never drift.
TASK_TIERS: dict[str, str] = {
    # fast — deepseek-v4-flash, thinking off: cheap, deterministic tasks
    "scope": "fast",
    "tool_selection": "fast",
    "safety_check": "fast",
    "parsing": "fast",
    # balanced — deepseek-v4-flash, thinking on: moderate reasoning
    "planning": "balanced",
    "steering": "balanced",
    "consensus": "balanced",
    "vector_generation": "balanced",
    "reporting": "balanced",
    # capable — deepseek-v4-pro, thinking on: hardest creative/offensive tasks
    "exploit_crafting": "capable",
    "poc_generation": "capable",
    "post_exploitation": "capable",
}

# Tier → concrete DeepSeek model. Mirrors `[models.<tier>]` in config/tensorzero.toml.
# Used to attribute real model names (and therefore cost) to each inference; the drift
# test keeps it aligned with the gateway config.
TIER_MODELS: dict[str, str] = {
    "fast": "deepseek-v4-flash",
    "balanced": "deepseek-v4-flash",
    "capable": "deepseek-v4-pro",
}

# Tier used when a task has no explicit mapping (matches `[functions.default]`).
DEFAULT_TIER = "balanced"


def resolve_model_for_function(function_name: str) -> str:
    """Resolve the concrete DeepSeek model a TensorZero function routes to."""
    tier = TASK_TIERS.get(function_name, DEFAULT_TIER)
    return TIER_MODELS.get(tier, TIER_MODELS[DEFAULT_TIER])


class TensorZeroRouter(LLMClient):
    """
    Smart LLM router powered by TensorZero gateway.

    All inference requests are routed through the TensorZero gateway,
    which handles multi-provider routing, fallbacks, A/B testing,
    observability, and optimization.
    """

    provider = "tensorzero"

    def __init__(self, gateway_url: str = ""):
        settings = get_ai_settings()
        self._gateway_url = (gateway_url or settings.TENSORZERO_GATEWAY_URL).rstrip("/")
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Lazy-initialize the HTTP client."""
        settings = get_ai_settings()
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._gateway_url,
                timeout=httpx.Timeout(settings.LLM_TIMEOUT, connect=10.0),
            )
        return self._client

    def _get_function_for_task(self, task_type: str | None) -> str:
        """Map a Spectra task type to a TensorZero function name."""
        if task_type and task_type in TASK_TIERS:
            return task_type
        return "default"

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float | None = None,
        task_type: str | None = None,
    ) -> LLMResponse:
        """Generate text via TensorZero gateway."""
        settings = get_ai_settings()
        function_name = self._get_function_for_task(task_type)

        messages = []
        messages.append({"role": "user", "content": [{"type": "text", "text": prompt}]})

        input_data: dict[str, Any] = {"messages": messages}
        if system_prompt:
            input_data["system"] = system_prompt

        payload: dict[str, Any] = {
            "function_name": function_name,
            "input": input_data,
            "params": {
                "chat_completion": {
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
            },
        }

        start_time = time.time()
        client = self._get_client()

        try:
            response = await client.post(
                "/inference",
                json=payload,
                timeout=timeout or settings.LLM_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()

            content = ""
            if data.get("content"):
                for block in data["content"]:
                    if block.get("type") == "text":
                        content += block.get("text", "")

            usage = data.get("usage", {})
            variant = data.get("variant_name", "default")
            # Record the concrete DeepSeek model (not the function/variant) so cost and
            # token attribution resolve against real per-model pricing.
            model = resolve_model_for_function(function_name)
            inference_id = data.get("inference_id", "")

            duration_ms = (time.time() - start_time) * 1000
            total_tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

            logger.debug(
                "TensorZero [%s -> %s/%s] %.0fms tokens=%d id=%s",
                function_name,
                model,
                variant,
                duration_ms,
                total_tokens,
                inference_id,
            )

            await record_llm_call(
                provider=self.provider,
                model=model,
                duration_ms=duration_ms,
                tokens=total_tokens,
                success=True,
            )

            return LLMResponse(
                content=content,
                model=model,
                provider=self.provider,
                usage={
                    "prompt_tokens": usage.get("input_tokens", 0),
                    "completion_tokens": usage.get("output_tokens", 0),
                    "total_tokens": total_tokens,
                },
                raw={
                    "inference_id": inference_id,
                    "episode_id": data.get("episode_id", ""),
                    "function_name": function_name,
                    "variant_name": variant,
                },
            )

        except httpx.HTTPStatusError as e:
            duration_ms = (time.time() - start_time) * 1000
            await record_llm_call(
                provider=self.provider,
                model=resolve_model_for_function(function_name),
                duration_ms=duration_ms,
                tokens=0,
                success=False,
            )
            error_body = e.response.text[:500] if e.response else ""
            logger.error("TensorZero HTTP error %s for %s: %s", e.response.status_code, function_name, error_body)
            raise RuntimeError(f"TensorZero gateway error ({e.response.status_code}): {error_body}") from e

        except (httpx.ConnectError, httpx.TimeoutException, OSError) as e:
            duration_ms = (time.time() - start_time) * 1000
            await record_llm_call(
                provider=self.provider,
                model=resolve_model_for_function(function_name),
                duration_ms=duration_ms,
                tokens=0,
                success=False,
            )
            logger.error("TensorZero connection error for %s: %s", function_name, e)
            raise RuntimeError(f"TensorZero gateway unreachable: {e}") from e

    async def stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float | None = None,
        task_type: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream tokens via TensorZero gateway."""
        settings = get_ai_settings()
        function_name = self._get_function_for_task(task_type)

        messages = []
        messages.append({"role": "user", "content": [{"type": "text", "text": prompt}]})

        input_data: dict[str, Any] = {"messages": messages}
        if system_prompt:
            input_data["system"] = system_prompt

        payload: dict[str, Any] = {
            "function_name": function_name,
            "input": input_data,
            "stream": True,
            "params": {
                "chat_completion": {
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
            },
        }

        client = self._get_client()

        async with client.stream(
            "POST",
            "/inference",
            json=payload,
            timeout=timeout or settings.LLM_TIMEOUT,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    import json

                    chunk = json.loads(data_str)
                    for block in chunk.get("content", []):
                        if block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                yield text
                except (ValueError, KeyError):
                    continue

    async def send_feedback(
        self,
        inference_id: str,
        metric_name: str,
        value: bool | float,
    ) -> None:
        """Send feedback to TensorZero for optimization."""
        client = self._get_client()
        try:
            response = await client.post(
                "/feedback",
                json={
                    "metric_name": metric_name,
                    "inference_id": inference_id,
                    "value": value,
                },
                timeout=10.0,
            )
            response.raise_for_status()
        except (httpx.HTTPError, OSError) as e:
            logger.warning("Failed to send feedback to TensorZero: %s", e)

    async def health_check(self) -> bool:
        """Check if TensorZero gateway is reachable."""
        try:
            client = self._get_client()
            response = await client.get("/health", timeout=5.0)
            return response.status_code == 200
        except (httpx.HTTPError, OSError):
            return False

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


def create_smart_router() -> LLMClient:
    """Create a TensorZero router from current settings."""
    gateway_url = get_ai_settings().TENSORZERO_GATEWAY_URL
    if not gateway_url:
        raise ValueError(
            "TENSORZERO_GATEWAY_URL is not configured. "
            "Set it to the TensorZero gateway address (e.g., http://tensorzero:3000)"
        )

    router = TensorZeroRouter(gateway_url=gateway_url)
    logger.info("TensorZero router created: %s", gateway_url)
    return router


# Singleton
_smart_router: LLMClient | None = None


def get_smart_router() -> LLMClient:
    """Get the global smart router instance."""
    global _smart_router
    if _smart_router is None:
        _smart_router = create_smart_router()
    return _smart_router


async def close_smart_router() -> None:
    """Close the smart router."""
    global _smart_router
    if _smart_router:
        await _smart_router.close()
        _smart_router = None
