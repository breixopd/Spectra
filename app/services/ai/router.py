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

from app.core.config import settings
from app.core.telemetry import record_llm_call
from app.services.ai.llm import LLMClient, LLMResponse

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Task complexity tiers — determines which TensorZero function to use
TASK_TIERS = {
    # Tier 1: Simple, deterministic tasks → cheapest/fastest model
    "scope": 1,
    "tool_selection": 1,
    "safety_check": 1,
    "parsing": 1,
    # Tier 2: Moderate reasoning → mid-tier model
    "planning": 2,
    "steering": 2,
    "consensus": 2,
    "vector_generation": 2,
    "reporting": 2,
    # Tier 3: Complex creative tasks → most capable model
    "exploit_crafting": 3,
    "poc_generation": 3,
    "post_exploitation": 3,
}

class TensorZeroRouter(LLMClient):
    """
    Smart LLM router powered by TensorZero gateway.

    All inference requests are routed through the TensorZero gateway,
    which handles multi-provider routing, fallbacks, A/B testing,
    observability, and optimization.
    """

    provider = "tensorzero"

    def __init__(self, gateway_url: str = ""):
        self._gateway_url = (gateway_url or settings.TENSORZERO_GATEWAY_URL).rstrip("/")
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Lazy-initialize the HTTP client."""
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
        function_name = self._get_function_for_task(task_type)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": [{"type": "text", "value": system_prompt}]})
        messages.append({"role": "user", "content": [{"type": "text", "value": prompt}]})

        payload: dict[str, Any] = {
            "function_name": function_name,
            "input": {"messages": messages},
            "params": {
                "temperature": temperature,
                "max_tokens": max_tokens,
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
            model = data.get("variant_name", function_name)
            inference_id = data.get("inference_id", "")

            duration_ms = (time.time() - start_time) * 1000
            total_tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

            logger.debug(
                "TensorZero [%s/%s] %.0fms tokens=%d id=%s",
                function_name,
                model,
                duration_ms,
                total_tokens,
                inference_id,
            )

            await record_llm_call(
                provider=self.provider,
                model=f"{function_name}/{model}",
                duration_ms=duration_ms,
                tokens=total_tokens,
                success=True,
            )

            return LLMResponse(
                content=content,
                model=f"{function_name}/{model}",
                provider=self.provider,
                usage={
                    "prompt_tokens": usage.get("input_tokens", 0),
                    "completion_tokens": usage.get("output_tokens", 0),
                    "total_tokens": total_tokens,
                },
                raw={
                    "inference_id": inference_id,
                    "episode_id": data.get("episode_id", ""),
                },
            )

        except httpx.HTTPStatusError as e:
            duration_ms = (time.time() - start_time) * 1000
            await record_llm_call(
                provider=self.provider,
                model=function_name,
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
                model=function_name,
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
        function_name = self._get_function_for_task(task_type)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": [{"type": "text", "value": system_prompt}]})
        messages.append({"role": "user", "content": [{"type": "text", "value": prompt}]})

        payload: dict[str, Any] = {
            "function_name": function_name,
            "input": {"messages": messages},
            "stream": True,
            "params": {
                "temperature": temperature,
                "max_tokens": max_tokens,
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
    gateway_url = settings.TENSORZERO_GATEWAY_URL
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
