"""Minimal mock LLM client for development/testing without test dependencies."""

import logging

from app.services.ai.llm import LLMClient, LLMResponse

logger = logging.getLogger("spectra.services.ai.mock_client")


class MockLLMClient(LLMClient):
    """Mock LLM client used when AI_PROVIDER=mock."""

    provider = "mock"

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float | None = None,
        task_type: str | None = None,
    ) -> LLMResponse:
        content = '{"status": "mock", "response": "Mock LLM response for development"}'
        if "json" in prompt.lower():
            content = '{"result": "mock_response", "confidence": 0.5}'
        return LLMResponse(
            content=content,
            model="mock",
            provider="mock",
            usage={"total_tokens": 10},
        )

    async def health_check(self) -> bool:
        return True
