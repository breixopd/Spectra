"""Gateway client for the AI microservice.

All LLM/embedding/RAG calls are routed to the separate AI service over HTTP.
AI_SERVICE_URL must be set in production; when absent the gateway is inert
and methods raise RuntimeError so tests fail fast with a clear message.
"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.services.gateway.http_client import GatewayClient
from spectra_domain.ai import ChatRequest, EmbeddingRequest, RAGRequest

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
                "AI Gateway: AI_SERVICE_URL is not set — AI calls will fail. Set AI_SERVICE_URL to the ai-svc endpoint."
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
        payload = ChatRequest(messages=messages, tier=tier, **kwargs).model_dump(exclude_none=True)
        resp = await client.post(
            "/api/v1/ai/chat",
            json=payload,
        )
        return resp

    async def embed(self, texts: list[str], **kwargs) -> list[list[float]]:
        client = self._require_client()
        payload = EmbeddingRequest(texts=texts, **kwargs).model_dump(exclude_none=True)
        resp = await client.post(
            "/api/v1/ai/embeddings",
            json=payload,
        )
        return resp.get("embeddings", [])

    async def rag_search(self, query: str, **kwargs) -> list[dict]:
        if self.client:
            payload = RAGRequest(query=query, **kwargs).model_dump(exclude_none=True)
            resp = await self.client.post(
                "/api/v1/ai/rag",
                json=payload,
            )
            return resp.get("results", [])
        # Monolith fallback — call RAGService directly
        from spectra_ai.rag import RAGService

        svc = RAGService()
        results = await svc.search(query=query, top_k=kwargs.get("top_k", 5), filters=kwargs.get("filters"))
        return [
            {
                "content": r.document.content,
                "score": r.score,
                "doc_type": r.document.doc_type,
            }
            for r in results
        ]

    async def check_embeddings_status(self) -> dict:
        """Check embedding/RAG component health.

        Returns dict with ``functional`` (bool) and ``status`` (str).
        """
        if self.client:
            try:
                resp = await self.client.get("/health")
                # AI service /health includes tensorzero — treat reachable as healthy
                return {"functional": resp.get("status") in ("healthy", "degraded"), "status": resp.get("status", "unknown")}
            except Exception as exc:
                return {"functional": False, "status": f"unreachable: {type(exc).__name__}"}
        # Monolith fallback
        try:
            from spectra_ai.rag import RAGService

            rag = RAGService()
            if rag.is_functional:
                return {"functional": True, "status": "healthy"}
            return {"functional": False, "status": "fallback"}
        except (OSError, RuntimeError, ValueError, ImportError) as exc:
            return {"functional": False, "status": f"unavailable: {type(exc).__name__}"}

    async def check_llm_status(self) -> dict:
        """Check LLM router/provider health.

        Returns dict with ``available`` (bool), ``provider`` (str), and ``status`` (str).
        """
        if self.client:
            try:
                resp = await self.client.get("/health")
                reachable = resp.get("status") in ("healthy", "degraded")
                return {"available": reachable, "provider": "remote", "status": resp.get("status", "unknown")}
            except Exception as exc:
                return {"available": False, "provider": "unknown", "status": f"unreachable: {type(exc).__name__}"}
        # Monolith fallback
        try:
            from spectra_ai.router import get_smart_router

            router_instance = get_smart_router()
            provider = getattr(router_instance, "provider", "unknown")
            return {"available": router_instance is not None, "provider": provider, "status": f"configured: {provider}"}
        except (OSError, RuntimeError, ValueError, ImportError) as exc:
            return {"available": False, "provider": "unknown", "status": f"unavailable: {type(exc).__name__}"}

    async def close(self):
        if self.client:
            await self.client.close()


_instance: AIGateway | None = None


def get_ai_gateway() -> AIGateway:
    global _instance
    if _instance is None:
        _instance = AIGateway()
    return _instance


async def close_ai_gateway() -> None:
    """Close the singleton AI gateway HTTP client."""
    global _instance
    if _instance is not None:
        await _instance.close()
        _instance = None
