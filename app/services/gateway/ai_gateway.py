"""Gateway client for the AI microservice.

All LLM/embedding/RAG calls are routed to the separate AI service over HTTP.
AI_SERVICE_URL must be set in production; when absent the gateway is inert
and methods raise RuntimeError so tests fail fast with a clear message.
"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.services.gateway.http_client import GatewayClient

logger = logging.getLogger(__name__)


class AIGateway:
    """Thin HTTP proxy to the remote AI service."""

    def __init__(self):
        self.remote_url = settings.AI_SERVICE_URL
        if self.remote_url:
            service_secret = settings.SERVICE_AUTH_SECRET.get_secret_value()
            self.client = GatewayClient(self.remote_url, timeout=120, service_auth=service_secret)
            logger.info("AI Gateway: routing to %s", self.remote_url)
        else:
            self.client = None
            logger.warning(
                "AI Gateway: AI_SERVICE_URL is not set — AI calls will fail. "
                "Set AI_SERVICE_URL to the ai-svc endpoint."
            )

    def _require_client(self) -> GatewayClient:
        if self.client is None:
            raise RuntimeError(
                "AI Gateway is not configured: AI_SERVICE_URL is not set. "
                "Cannot route AI requests without a remote AI service."
            )
        return self.client

    async def chat(self, messages: list[dict], tier: int = 2, **kwargs) -> dict:
        client = self._require_client()
        resp = await client.post(
            "/api/v1/ai/chat",
            json={"messages": messages, "tier": tier, **kwargs},
        )
        return resp

    async def embed(self, texts: list[str], **kwargs) -> list[list[float]]:
        client = self._require_client()
        resp = await client.post(
            "/api/v1/ai/embeddings",
            json={"texts": texts, **kwargs},
        )
        return resp.get("embeddings", [])

    async def rag_search(self, query: str, **kwargs) -> list[dict]:
        client = self._require_client()
        resp = await client.post(
            "/api/v1/ai/rag",
            json={"query": query, **kwargs},
        )
        return resp.get("results", [])

    async def close(self):
        if self.client:
            await self.client.close()


_instance: AIGateway | None = None


def get_ai_gateway() -> AIGateway:
    global _instance
    if _instance is None:
        _instance = AIGateway()
    return _instance
