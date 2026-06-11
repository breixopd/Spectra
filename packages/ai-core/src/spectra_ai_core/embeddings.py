"""Embedding Service — local (fastembed) or API (OpenAI SDK).

By default uses fastembed for free local embeddings. Falls back to
OpenAI SDK when an API-backed model is configured.
"""

from __future__ import annotations

import asyncio
import logging
import os
from types import SimpleNamespace

logger = logging.getLogger(__name__)

# Default model can be overridden by services/ai at startup.
_default_embedding_model: str = "BAAI/bge-small-en-v1.5"

# Optional settings registry — services/ai can register a callable that returns settings.
_settings_factory = None


def register_settings_factory(factory) -> None:
    """Register a factory that returns AI settings. Called by services/ai."""
    global _settings_factory
    _settings_factory = factory


def get_ai_settings():
    """Return AI settings object. Uses registered factory or falls back to env vars."""
    if _settings_factory is not None:
        return _settings_factory()
    emb_key = os.environ.get("EMBEDDING_API_KEY") or os.environ.get("OPENAI_API_KEY") or None
    return SimpleNamespace(
        EMBEDDING_MODEL=os.environ.get("EMBEDDING_MODEL", _default_embedding_model),
        EMBEDDING_API_KEY=emb_key,
        EMBEDDING_API_BASE_URL=os.environ.get("EMBEDDING_API_BASE_URL", ""),
    )


def set_default_embedding_model(model: str) -> None:
    """Register the embedding model name. Called by services/ai at startup."""
    global _default_embedding_model
    if model:
        _default_embedding_model = model


class EmbeddingService:
    """Embedding service: local fastembed or OpenAI SDK API backend."""

    def __init__(self, model_name: str = ""):
        self.model_name = model_name or _default_embedding_model
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
        """True when embeddings can be produced."""
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
            if test:
                self._embedding_dim = len(test[0])
        except (ImportError, OSError, RuntimeError) as e:
            logger.warning("Failed to load fastembed model: %s", e)
            self._local_embedder = None

    async def _load_model(self) -> None:
        """Pre-load the embedding model.

        Prefers a configured API backend (EMBEDDING_API_KEY) so operators who
        point Spectra at a hosted embedding endpoint get it; otherwise falls back
        to the bundled local fastembed model.
        """
        if self._api_ready:
            return
        if self._configured_api_key():
            await self._init_api_backend()
            if self._api_ready:
                return

        try:
            from fastembed import TextEmbedding

            # The configured model_name may be a hosted/API model; the local
            # fallback always uses the bundled fastembed model.
            self._local_model_name = _default_embedding_model
            self._local_embedder = await asyncio.to_thread(TextEmbedding, model_name=self._local_model_name)
            test = await asyncio.to_thread(lambda: list(self._local_embedder.embed(["dim_probe"])))  # type: ignore[union-attr]
            if test:
                self._embedding_dim = len(test[0])
                self._api_ready = True
                self._use_local = True
                logger.info("Loaded local embedding model %s (dim=%d)", self._local_model_name, self._embedding_dim)
        except (ImportError, OSError, RuntimeError) as e:
            logger.warning("Local embedding model unavailable (%s), trying API backend", e)
            await self._init_api_backend()

    @staticmethod
    def _configured_api_key() -> str | None:
        """Return the configured embedding API key (EMBEDDING_API_KEY, else OPENAI_API_KEY)."""
        settings = get_ai_settings()
        for raw in (getattr(settings, "EMBEDDING_API_KEY", None), getattr(settings, "OPENAI_API_KEY", None)):
            if raw is None:
                continue
            value = raw.get_secret_value() if hasattr(raw, "get_secret_value") else str(raw)
            if value:
                return value
        return None

    async def _init_api_backend(self) -> None:
        """Initialize OpenAI-compatible API backend using settings."""
        try:
            from openai import AsyncOpenAI

            api_key = self._configured_api_key()
            if not api_key:
                logger.warning("No EMBEDDING_API_KEY or OPENAI_API_KEY — API embeddings disabled")
                return

            settings = get_ai_settings()
            base_url = getattr(settings, "EMBEDDING_API_BASE_URL", "") or None
            model = getattr(settings, "EMBEDDING_MODEL", "") or self.model_name or "text-embedding-3-small"

            kwargs: dict = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url

            self._openai_client = AsyncOpenAI(**kwargs)
            self._openai_model = model
            self._api_ready = True
            logger.info("Using API embedding backend: %s", self._openai_model)
        except (ImportError, OSError, RuntimeError) as e:
            logger.warning("API embedding backend also unavailable: %s", e)
            self._api_ready = False

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        if not self._api_ready:
            await self._load_model()
        if not self._api_ready:
            return [[] for _ in texts]

        if self._use_local and self._local_embedder:
            await self._ensure_local_loaded()
            try:
                raw = await asyncio.to_thread(lambda: list(self._local_embedder.embed(texts)))  # type: ignore[union-attr]
                return [list(v) for v in raw]
            except (OSError, RuntimeError) as e:
                logger.warning("Local embedding failed: %s", e)
                return [[] for _ in texts]

        if self._openai_client:
            try:
                resp = await self._openai_client.embeddings.create(  # type: ignore[union-attr]
                    model=self._openai_model,
                    input=texts,
                    encoding_format="float",
                )
                return [item.embedding for item in resp.data]
            except (OSError, RuntimeError) as e:
                logger.warning("API embedding failed: %s", e)
                return [[] for _ in texts]

        return [[] for _ in texts]

    async def embed_one(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        results = await self.embed([text])
        return results[0] if results else []
