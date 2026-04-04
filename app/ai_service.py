"""Spectra AI Service — LLM routing, embeddings, and RAG queries.

Runs as a separate microservice, exposing internal API for the core API service.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """AI service startup/shutdown."""
    logger.info("AI Service starting...")

    from app.services.ai.embeddings import EmbeddingService

    try:
        svc = EmbeddingService()
        await svc._load_model()
        logger.info("Embedding service initialized")
    except (OSError, RuntimeError, ImportError) as e:
        logger.warning("Embedding init failed (will retry on first use): %s", e)

    yield
    logger.info("AI Service shutting down")


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
    allow_methods=["*"],
    allow_headers=["*"],
)

# Service auth middleware
from app.core.service_auth import ServiceAuthMiddleware

_settings = _cors_settings
_secret = _settings.SERVICE_AUTH_SECRET.get_secret_value()
if _secret:
    app.add_middleware(ServiceAuthMiddleware, secret=_secret)


# --- Health ---
@app.get("/health")
async def health():
    return {"status": "healthy", "service": "ai"}


# --- LLM Chat ---
class ChatRequest(BaseModel):
    messages: list[dict]
    model: str | None = None
    tier: int = 2  # 1=fast, 2=balanced, 3=advanced
    temperature: float = 0.7
    max_tokens: int | None = None
    user_id: str | None = None  # For BYOK resolution


class ChatResponse(BaseModel):
    content: str
    model: str
    usage: dict = {}


@app.post("/api/v1/ai/chat", response_model=ChatResponse)
async def ai_chat(req: ChatRequest):
    """Route an LLM chat request through the smart router."""
    try:
        from app.services.ai.router import get_smart_router

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


# --- Embeddings ---
class EmbeddingRequest(BaseModel):
    texts: list[str]
    model: str | None = None
    user_id: str | None = None


class EmbeddingResponse(BaseModel):
    embeddings: list[list[float]]
    model: str
    dimensions: int


@app.post("/api/v1/ai/embeddings", response_model=EmbeddingResponse)
async def generate_embeddings(req: EmbeddingRequest):
    """Generate embeddings for a list of texts."""
    try:
        from app.services.ai.embeddings import EmbeddingService

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


# --- RAG Query ---
class RAGRequest(BaseModel):
    query: str
    collection: str = "default"
    top_k: int = 5
    filters: dict | None = None


class RAGResponse(BaseModel):
    results: list[dict]
    query: str


@app.post("/api/v1/ai/rag", response_model=RAGResponse)
async def rag_query(req: RAGRequest):
    """Search the RAG vector store."""
    try:
        from app.services.ai.rag import RAGService

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
