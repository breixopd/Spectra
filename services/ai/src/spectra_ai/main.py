"""Spectra AI Service — LLM routing, embeddings, and RAG queries.

Runs as a separate microservice, exposing internal API for the core API service.
"""

import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware

import app.core.database
import app.telemetry.telemetry
from spectra_domain.ai import ChatRequest, ChatResponse, EmbeddingRequest, EmbeddingResponse, RAGRequest, RAGResponse

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """AI service startup/shutdown."""
    logger.info("AI Service starting...")

    from spectra_ai.embeddings import EmbeddingService

    try:
        svc = EmbeddingService()
        await svc._load_model()
        logger.info("Embedding service initialized")
    except (OSError, RuntimeError, ImportError) as e:
        logger.warning("Embedding init failed (will retry on first use): %s", e)

    yield
    logger.info("AI Service shutting down...")

    # Close httpx clients used by AI router
    try:
        from spectra_ai.router import get_smart_router

        router = get_smart_router()
        if hasattr(router, "close"):
            await router.close()
    except Exception:
        logger.debug("AI router cleanup skipped", exc_info=True)

    # Unload embedding model
    try:
        from spectra_ai.embeddings import EmbeddingService

        svc = EmbeddingService()
        if hasattr(svc, "unload"):
            svc.unload()
    except Exception:
        logger.debug("Embedding cleanup skipped", exc_info=True)

    logger.info("AI Service shutdown complete")


app = FastAPI(
    title="Spectra AI Service",
    description="Internal LLM routing, embeddings, and RAG",
    version="1.0.0",
    lifespan=lifespan,
)

from app.core.config import get_settings as _get_cors_settings

_cors_settings = _get_cors_settings()
_cors_origins = (
    _cors_settings.CORS_ORIGINS
    if _cors_settings.CORS_ORIGINS
    else [
        "http://spectra-app:5000",
        "http://app:5000",
        "http://localhost:5000",
    ]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-Service-Auth"],
)

# Service auth middleware
from app.di.service_auth import ServiceAuthMiddleware

_settings = _cors_settings
_secret = _settings.SERVICE_AUTH_SECRET.get_secret_value()
if _secret:
    app.add_middleware(ServiceAuthMiddleware, secret=_secret)


# --- Health ---
@app.get("/healthz")
async def healthz():
    return {"status": "alive", "service": "ai"}


@app.get("/health", response_model=None)
async def health(response = None):
    import httpx

    result = {"status": "healthy", "service": "ai"}
    try:
        tz_url = getattr(_settings, "TENSORZERO_GATEWAY_URL", "") or "http://tensorzero:3000"
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{tz_url.rstrip('/')}/health")
            if resp.status_code == 200:
                result["tensorzero"] = "reachable"
            else:
                result["tensorzero"] = "degraded"
                result["status"] = "degraded"
                if response is not None:
                    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    except Exception:
        result["tensorzero"] = "unreachable"
        result["status"] = "degraded"
        if response is not None:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result


@app.get("/health/ready")
async def health_ready(response: Response):
    import httpx

    checks: dict[str, Any] = {}
    overall = True

    tz_url = getattr(_settings, "TENSORZERO_GATEWAY_URL", "") or "http://tensorzero:3000"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{tz_url.rstrip('/')}/health")
        checks["tensorzero"] = resp.status_code == 200
    except Exception:
        checks["tensorzero"] = False
    overall = overall and checks["tensorzero"]

    try:
        from spectra_ai.embeddings import EmbeddingService

        svc = EmbeddingService()
        await svc._load_model()
        checks["embeddings"] = svc.is_functional
    except Exception:
        checks["embeddings"] = False
    overall = overall and checks["embeddings"]

    try:
        from spectra_ai.rag import RAGService

        rag = RAGService()
        checks["rag"] = rag.is_functional
    except Exception:
        checks["rag"] = False
    overall = overall and checks["rag"]

    if not overall:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"ready": overall, "checks": checks, "status": "healthy" if overall else "degraded"}


@app.get("/health/deep")
async def health_deep(response: Response):
    start = time.time()
    try:
        from spectra_ai.router import get_smart_router

        router = get_smart_router()
        result = await router.generate(
            prompt="ok",
            max_tokens=1,
            task_type="parsing",
            temperature=0.0,
        )
        if result.content:
            latency_ms = round((time.time() - start) * 1000, 1)
            return {
                "status": "healthy",
                "service": "ai",
                "llm": {"status": "healthy", "latency_ms": latency_ms, "response": result.content[:50]},
            }
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "service": "ai", "llm": {"status": "degraded", "error": "empty response"}}
    except Exception as exc:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "service": "ai", "llm": {"status": "unhealthy", "error": type(exc).__name__}}


@app.post("/api/v1/ai/chat", response_model=ChatResponse)
async def ai_chat(req: ChatRequest):
    """Route an LLM chat request through the smart router."""
    try:
        from spectra_ai.router import get_smart_router

        router = get_smart_router()

        # Build task_type from tier for model routing
        tier_task_map = {1: "parsing", 2: "planning", 3: "exploit_crafting"}
        task_type = tier_task_map.get(req.tier, "planning")

        # Join messages into prompt (last user message) + system prompt
        system_prompt = None
        prompt = ""
        for msg in req.messages:
            if msg.get("role") == "system":
                system_prompt = msg.get("content", "")
            elif msg.get("role") == "user":
                prompt = msg.get("content", "")

        result = await router.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=req.temperature,
            max_tokens=req.max_tokens or 2048,
            task_type=task_type,
        )
        return ChatResponse(
            content=result.content,
            model=result.model,
            usage=result.usage,
        )
    except (OSError, RuntimeError, ValueError, TimeoutError):
        logger.exception("AI chat error")
        raise HTTPException(500, "Internal service error")


@app.post("/api/v1/ai/embeddings", response_model=EmbeddingResponse)
async def generate_embeddings(req: EmbeddingRequest):
    """Generate embeddings for a list of texts."""
    try:
        from spectra_ai.embeddings import EmbeddingService

        svc = EmbeddingService(model_name=req.model or "")
        await svc._load_model()
        embeddings = await svc.embed_batch(req.texts)
        return EmbeddingResponse(
            embeddings=embeddings,
            model=svc.model_name or "unknown",
            dimensions=len(embeddings[0]) if embeddings else 0,
        )
    except (OSError, RuntimeError, ValueError, TimeoutError):
        logger.exception("Embedding error")
        raise HTTPException(500, "Internal service error")


@app.post("/api/v1/ai/rag", response_model=RAGResponse)
async def rag_query(req: RAGRequest):
    """Search the RAG vector store."""
    try:
        from spectra_ai.rag import RAGService

        svc = RAGService()
        results = await svc.search(
            query=req.query,
            top_k=req.top_k,
            filters=req.filters,
        )
        return RAGResponse(
            results=[
                {
                    "content": r.document.content,
                    "score": r.score,
                    "metadata": r.document.metadata,
                }
                for r in results
            ],
            query=req.query,
        )
    except (OSError, RuntimeError, ValueError, TimeoutError):
        logger.exception("RAG query error")
        raise HTTPException(500, "Internal service error")
