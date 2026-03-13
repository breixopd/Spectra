"""Gateway client for the AI microservice.

When AI_SERVICE_URL is set, LLM/embedding/RAG calls are routed to the
separate AI service over HTTP. When empty, calls go in-process (monolith mode).
"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.services.gateway.http_client import GatewayClient

logger = logging.getLogger("spectra.ai_gateway")


class AIGateway:
    """Routes AI requests to either in-process or remote AI service."""

    def __init__(self):
        self.remote_url = settings.AI_SERVICE_URL
        if self.remote_url:
            service_secret = settings.SERVICE_AUTH_SECRET.get_secret_value()
            self.client = GatewayClient(self.remote_url, timeout=120, service_auth=service_secret)
            logger.info("AI Gateway: routing to %s", self.remote_url)
        else:
            self.client = None
            logger.info("AI Gateway: using in-process AI services")

    @property
    def is_remote(self) -> bool:
        return bool(self.remote_url)

    async def chat(self, messages: list[dict], tier: int = 2, **kwargs) -> dict:
        if self.is_remote:
            assert self.client is not None
            resp = await self.client.post(
                "/api/v1/ai/chat",
                json={"messages": messages, "tier": tier, **kwargs},
            )
            return resp
        else:
            from app.services.ai.router import get_smart_router

            router = get_smart_router()
            tier_task_map = {1: "parsing", 2: "planning", 3: "exploit_crafting"}
            task_type = tier_task_map.get(tier, "planning")

            system_prompt = None
            prompt = ""
            for msg in messages:
                if msg.get("role") == "system":
                    system_prompt = msg.get("content", "")
                elif msg.get("role") == "user":
                    prompt = msg.get("content", "")

            result = await router.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                task_type=task_type,
                **kwargs,
            )
            return {"content": result.content, "model": result.model, "usage": result.usage}

    async def embed(self, texts: list[str], **kwargs) -> list[list[float]]:
        if self.is_remote:
            assert self.client is not None
            resp = await self.client.post(
                "/api/v1/ai/embeddings",
                json={"texts": texts, **kwargs},
            )
            return resp.get("embeddings", [])
        else:
            from app.services.ai.embeddings import EmbeddingService

            svc = EmbeddingService()
            await svc._load_model()
            return await svc.embed_batch(texts)

    async def rag_search(self, query: str, **kwargs) -> list[dict]:
        if self.is_remote:
            assert self.client is not None
            resp = await self.client.post(
                "/api/v1/ai/rag",
                json={"query": query, **kwargs},
            )
            return resp.get("results", [])
        else:
            from app.services.ai.rag import RAGService

            svc = RAGService()
            results = await svc.search(query=query, **kwargs)
            return [{"content": r.content, "score": r.score, "metadata": r.metadata} for r in results]

    async def close(self):
        if self.client:
            await self.client.close()


_instance: AIGateway | None = None


def get_ai_gateway() -> AIGateway:
    global _instance
    if _instance is None:
        _instance = AIGateway()
    return _instance
