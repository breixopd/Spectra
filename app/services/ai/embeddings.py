"""
Embedding Service.

Supports three backends:
- **local**: sentence-transformers (no API needed, runs on CPU/GPU)
- **api**: LiteLLM embedding API (OpenAI, DashScope, etc.)
- **fallback**: Deterministic SHA256 hashing (testing only, no semantic meaning)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import struct
from typing import Any

from app.core.config import settings

logger = logging.getLogger("spectra.ai.embeddings")


class EmbeddingService:
    """
    Embedding service with local, API, and fallback backends.

    Backend is selected via EMBEDDING_PROVIDER setting:
    - "local": sentence-transformers (default if available)
    - "api": LiteLLM API using LLM_API_KEY / LLM_API_BASE_URL
    - "fallback": SHA256 hashing (testing only)
    - "": auto-detect (local → api → fallback)
    """

    def __init__(self, model_name: str = ""):
        self.model_name = model_name or settings.EMBEDDING_MODEL
        self._use_fallback = False
        self._use_local = False
        self._api_ready = False
        self._init_lock: asyncio.Lock | None = None
        self._litellm_model: str = ""
        self._litellm_kwargs: dict = {}
        self._local_model: Any = None
        self._embedding_dim: int | None = None

    @property
    def is_functional(self) -> bool:
        """Return True if real embeddings are available (local or API)."""
        return self._api_ready and not self._use_fallback

    @property
    def embedding_dim(self) -> int | None:
        """Return the embedding dimension if known."""
        return self._embedding_dim

    async def _load_model(self) -> None:
        """Configure embedding backend: local, API, or fallback."""
        if self._api_ready or self._use_fallback:
            return

        if self._init_lock is None:
            self._init_lock = asyncio.Lock()

        async with self._init_lock:
            if self._api_ready or self._use_fallback:
                return

            provider = settings.EMBEDDING_PROVIDER.lower() if settings.EMBEDDING_PROVIDER else ""

            if provider == "local":
                await self._init_local()
            elif provider == "api":
                await self._init_api()
            elif provider == "fallback" or settings.AI_PROVIDER == "mock":
                self._use_fallback = True
            else:
                # Auto-detect: try local first, then API, then fallback
                if await self._try_init_local():
                    return
                if await self._try_init_api():
                    return
                logger.info("No embedding backend available, using SHA256 fallback")
                self._use_fallback = True

    async def _init_local(self) -> None:
        """Initialize local sentence-transformers backend."""
        try:
            from sentence_transformers import SentenceTransformer

            model_name = self.model_name if self.model_name != "text-embedding-3-small" else "all-MiniLM-L6-v2"
            self._local_model = await asyncio.to_thread(SentenceTransformer, model_name)
            self._embedding_dim = self._local_model.get_sentence_embedding_dimension()
            self._api_ready = True
            self._use_local = True
            logger.info("Local embedding service ready: model=%s (dim=%d)", model_name, self._embedding_dim)
        except ImportError as e:
            raise RuntimeError(
                "Local embeddings require sentence-transformers. "
                "Rebuild with ENABLE_LOCAL_EMBEDDINGS=true or switch to API embeddings "
                "(EMBEDDING_PROVIDER=api)."
            ) from e
        except Exception as e:
            raise RuntimeError(f"Failed to load local embedding model: {e}") from e

    async def _try_init_local(self) -> bool:
        """Try to initialize local embeddings, return True on success."""
        try:
            await self._init_local()
            return True
        except Exception:
            return False

    async def _init_api(self) -> None:
        """Initialize LiteLLM API backend."""
        if not settings.LLM_API_KEY.get_secret_value():
            raise RuntimeError("LLM_API_KEY not configured for API embeddings")

        import litellm  # noqa: F401

        api_key = settings.LLM_API_KEY.get_secret_value()
        base_url = settings.LLM_API_BASE_URL

        if base_url:
            self._litellm_model = f"openai/{self.model_name}"
            self._litellm_kwargs = {"api_base": base_url, "api_key": api_key}
        else:
            self._litellm_model = self.model_name
            self._litellm_kwargs = {"api_key": api_key}

        self._api_ready = True
        logger.info("Embedding service ready: model=%s", self._litellm_model)

    async def _try_init_api(self) -> bool:
        """Try to initialize API embeddings, return True on success."""
        try:
            await self._init_api()
            return True
        except Exception:
            return False

    async def embed(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        await self._load_model()

        if self._use_fallback:
            return self._fallback_embed(text)

        if self._use_local:
            return await self._local_embed(text)

        import litellm

        for attempt in range(2):
            try:
                response = await litellm.aembedding(
                    model=self._litellm_model,
                    input=[text],
                    encoding_format="float",
                    **self._litellm_kwargs,
                )
                return response.data[0]["embedding"]
            except Exception as e:
                if attempt == 0:
                    logger.warning("Embedding attempt failed, retrying: %s", e)
                    continue
                logger.error("Embedding failed after retry: %s. Using fallback.", e)
                return self._fallback_embed(text)
        return self._fallback_embed(text)  # unreachable; satisfies type checker

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        await self._load_model()

        if self._use_fallback:
            return [self._fallback_embed(t) for t in texts]

        if not texts:
            return []

        if self._use_local:
            return await self._local_embed_batch(texts)

        import litellm

        for attempt in range(2):
            try:
                response = await litellm.aembedding(
                    model=self._litellm_model,
                    input=texts,
                    encoding_format="float",
                    **self._litellm_kwargs,
                )
                return [item["embedding"] for item in response.data]
            except Exception as e:
                if attempt == 0:
                    logger.warning("Batch embedding attempt failed, retrying: %s", e)
                    continue
                logger.error("Batch embedding failed after retry: %s. Using fallback.", e)
                return [self._fallback_embed(t) for t in texts]
        return [self._fallback_embed(t) for t in texts]  # unreachable; satisfies type checker

    async def _local_embed(self, text: str) -> list[float]:
        """Generate embedding using local sentence-transformers model."""
        embedding = await asyncio.to_thread(self._local_model.encode, text, normalize_embeddings=True)
        return embedding.tolist()

    async def _local_embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate batch embeddings using local sentence-transformers model."""
        embeddings = await asyncio.to_thread(self._local_model.encode, texts, normalize_embeddings=True)
        return embeddings.tolist()

    def _fallback_embed(self, text: str, dim: int = 384) -> list[float]:
        """Deterministic fallback embedding using SHA256 hashing."""
        text_hash = hashlib.sha256(text.lower().encode()).digest()

        extended = text_hash
        while len(extended) < dim * 4:
            extended += hashlib.sha256(extended).digest()

        floats = []
        for i in range(dim):
            val = struct.unpack("f", extended[i * 4 : (i + 1) * 4])[0]
            floats.append(max(-1.0, min(1.0, val / 1e38)))

        magnitude = sum(f * f for f in floats) ** 0.5
        if magnitude > 0:
            floats = [f / magnitude for f in floats]

        return floats
