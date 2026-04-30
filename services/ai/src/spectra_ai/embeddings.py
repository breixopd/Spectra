"""Embedding Service — local (fastembed) or API (OpenAI SDK).

By default uses fastembed for free local embeddings.  Falls back to
OpenAI SDK when an API-backed model is configured.
"""

from __future__ import annotations

import asyncio
import logging

from spectra_ai.settings import get_ai_settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Embedding service: local fastembed or OpenAI SDK API backend."""

    def __init__(self, model_name: str = ""):
        settings = get_ai_settings()
        self.model_name = model_name or settings.EMBEDDING_MODEL
        self._api_ready = False
        self._use_local = False
        self._local_embedder: object | None = None
        self._local_model_name: str = ""
        self._init_lock: asyncio.Lock | None = None
        self._openai_client: object | None = None
        self._openai_model: str = ""
        self._embedding_dim: int | None = None

    @property
    def is_functional(self) -> bool:
        """True when embeddings can be produced (local path configured or API client ready)."""
        return self._api_ready

    @property
    def embedding_dim(self) -> int | None:
        """Return the embedding dimension if known."""
        return self._embedding_dim

    async def _ensure_local_loaded(self) -> None:
        """Lazy-load the local fastembed model on first use."""
        if self._local_embedder is not None:
            return
        try:
            from fastembed import TextEmbedding

            self._local_embedder = await asyncio.to_thread(TextEmbedding, model_name=self._local_model_name)
            test = await asyncio.to_thread(lambda: list(self._local_embedder.embed(["dim_probe"])))  # type: ignore[union-attr]
            self._embedding_dim = len(test[0])
            logger.info("Local embedding model loaded: %s dim=%d", self._local_model_name, self._embedding_dim)
        except (OSError, RuntimeError, ImportError) as e:
            self._api_ready = False
            raise RuntimeError(f"Failed to load local embedding model '{self._local_model_name}': {e}") from e

    async def _load_model(self) -> None:
        """Configure API backend via OpenAI SDK."""
        if self._api_ready:
            return

        if self._init_lock is None:
            self._init_lock = asyncio.Lock()

        async with self._init_lock:
            if self._api_ready:
                return

            settings = get_ai_settings()
            # Check if using local embedding model
            model_lower = self.model_name.lower()
            api_key = settings.EMBEDDING_API_KEY.get_secret_value()

            if model_lower.startswith("local/") or (not api_key):
                # Mark as local — actual model download is deferred to first embed() call
                self._local_model_name = (
                    self.model_name.removeprefix("local/")
                    if model_lower.startswith("local/")
                    else "BAAI/bge-small-en-v1.5"
                )
                self._use_local = True
                self._api_ready = True
                logger.info(
                    "Local embedding configured (lazy): model=%s (downloaded on first use)", self._local_model_name
                )
                return

            from openai import AsyncOpenAI

            base_url = settings.EMBEDDING_API_BASE_URL

            self._openai_client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url or None,
            )
            self._openai_model = self.model_name

            self._api_ready = True
            logger.info("Embedding service ready: model=%s", self._openai_model)

    async def embed(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        await self._load_model()

        if not self._api_ready:
            raise RuntimeError(
                "Embedding service not configured. Set EMBEDDING_API_KEY or use a local model (EMBEDDING_MODEL=local/BAAI/bge-small-en-v1.5)."
            )

        if self._use_local:
            await self._ensure_local_loaded()
            embeddings = await asyncio.to_thread(lambda: list(self._local_embedder.embed([text])))  # type: ignore[union-attr]
            return embeddings[0].tolist()

        for attempt in range(2):
            try:
                response = await self._openai_client.embeddings.create(  # type: ignore[union-attr]
                    model=self._openai_model,
                    input=[text],
                    encoding_format="float",
                )
                return response.data[0].embedding
            except (OSError, RuntimeError, ValueError, TimeoutError) as e:
                if attempt == 0:
                    logger.warning("Embedding attempt failed, retrying: %s", e)
                    continue
                raise RuntimeError(f"Embedding failed after retry: {e}") from e
        raise RuntimeError("Embedding failed")  # unreachable; satisfies type checker

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        await self._load_model()

        if not self._api_ready:
            raise RuntimeError("Embedding service not configured.")

        if not texts:
            return []

        if self._use_local:
            await self._ensure_local_loaded()
            embeddings = await asyncio.to_thread(lambda: list(self._local_embedder.embed(texts)))  # type: ignore[union-attr]
            return [e.tolist() for e in embeddings]

        for attempt in range(2):
            try:
                response = await self._openai_client.embeddings.create(  # type: ignore[union-attr]
                    model=self._openai_model,
                    input=texts,
                    encoding_format="float",
                )
                return [item.embedding for item in response.data]
            except (OSError, RuntimeError, ValueError, TimeoutError) as e:
                if attempt == 0:
                    logger.warning("Batch embedding attempt failed, retrying: %s", e)
                    continue
                raise RuntimeError(f"Batch embedding failed after retry: {e}") from e
        raise RuntimeError("Batch embedding failed")  # unreachable; satisfies type checker
