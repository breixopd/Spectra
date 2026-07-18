"""LLMClient adapter for the split API -> AI service deployment.

Mission orchestration lives in the API process, while model execution usually
lives in ``ai-svc``.  Keeping this adapter in the bounded ai-core package lets
all agents use the same LLMClient contract in either topology and prevents a
split deployment from accidentally starting without a registered factory.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from spectra_ai_core.gateway.ai_gateway import AIGateway, get_ai_gateway
from spectra_ai_core.llm import LLMClient, LLMResponse


class GatewayLLMClient(LLMClient):
    """Translate the internal LLMClient interface to AIGateway HTTP calls."""

    provider = "ai-gateway"

    def __init__(self, gateway: AIGateway | None = None):
        self.gateway = gateway or get_ai_gateway()

    @staticmethod
    def _tier_for_task(task_type: str | None) -> int:
        return {
            "parsing": 1,
            "output_parsing": 1,
            "planning": 2,
            "tool_selection": 2,
            "replan": 2,
            "exploit_crafting": 3,
            "payload": 3,
        }.get((task_type or "").lower(), 2)

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float | None = None,
        task_type: str | None = None,
    ) -> LLMResponse:
        del timeout  # GatewayClient owns the bounded HTTP timeout.
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = await self.gateway.chat(
            messages,
            tier=self._tier_for_task(task_type),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return LLMResponse(
            content=str(payload.get("content", "")),
            model=str(payload.get("model", "remote")),
            provider=self.provider,
            usage=dict(payload.get("usage") or {}),
            raw=payload,
        )

    async def stream(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float | None = None,
        task_type: str | None = None,
    ) -> AsyncIterator[str]:
        # The internal AI API currently exposes a non-streaming contract. Keep
        # the LLMClient stream shape so callers remain topology-independent.
        response = await self.generate(prompt, system_prompt, temperature, max_tokens, timeout, task_type)
        yield response.content

    async def health_check(self) -> bool:
        status = await self.gateway.check_llm_status()
        return bool(status.get("available"))

    async def close(self) -> None:
        await self.gateway.close()
