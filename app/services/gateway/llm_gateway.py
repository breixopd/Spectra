"""HTTP client adapter for remote LLM gateway service."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.core.telemetry import record_llm_call
from app.services.ai.llm import LLMClient, LLMResponse
from app.services.gateway.http_client import GatewayClient

logger = logging.getLogger("spectra.gateway.llm")


class LLMGatewayClient(LLMClient):
    """Routes LLM calls to an external gateway via HTTP."""

    provider = "gateway"

    def __init__(self, base_url: str, *, timeout: int = 120, api_key: str = ""):
        self._client = GatewayClient(base_url, timeout=timeout, api_key=api_key)

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float | None = None,
        task_type: str | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "prompt": prompt,
            "system_prompt": system_prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "task_type": task_type,
        }
        start_time = time.time()
        try:
            data = await self._client.post("/v1/chat/completions", json=payload)
            duration_ms = (time.time() - start_time) * 1000
            usage = data.get("usage", {})
            tokens = usage.get("total_tokens", 0) if isinstance(usage, dict) else 0
            await record_llm_call(
                provider="gateway",
                model=data.get("model", "unknown"),
                duration_ms=duration_ms,
                tokens=tokens,
                success=True,
            )
            return LLMResponse(
                content=data.get("content", ""),
                model=data.get("model", "unknown"),
                provider="gateway",
                usage=usage,
            )
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            await record_llm_call(
                provider="gateway",
                model="unknown",
                duration_ms=duration_ms,
                tokens=0,
                success=False,
            )
            raise

    async def generate_structured(
        self,
        prompt: str,
        response_model: type | None = None,
        system_prompt: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        timeout: float | None = None,
        task_type: str | None = None,
    ) -> Any:
        payload: dict[str, Any] = {
            "prompt": prompt,
            "system_prompt": system_prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "task_type": task_type,
        }
        if response_model and hasattr(response_model, "model_json_schema"):
            payload["schema"] = response_model.model_json_schema()
        data = await self._client.post("/v1/chat/structured", json=payload)
        if response_model and hasattr(response_model, "model_validate"):
            return response_model.model_validate(data.get("result", data))
        return data

    async def health_check(self) -> bool:
        try:
            result = await self._client.health_check()
            return result.get("status") == "healthy"
        except Exception:
            return False

    async def close(self) -> None:
        await self._client.close()
