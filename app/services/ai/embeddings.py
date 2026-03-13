"""
Embedding Service — API-only via LiteLLM.

Requires a configured LLM_API_KEY. If no key is available, the service
reports as non-functional and raises a clear error on use.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings

logger = logging.getLogger("spectra.ai.embeddings")


class EmbeddingService:
    """Embedding service using LiteLLM API backend.

    Requires LLM_API_KEY to be configured. If unavailable, ``is_functional``
    returns False and ``embed``/``embed_batch`` raise RuntimeError.
    """

    def __init__(self, model_name: str = ""):
        self.model_name = model_name or settings.EMBEDDING_MODEL
        self._api_ready = False
        self._init_lock: asyncio.Lock | None = None
        self._litellm_model: str = ""
        self._litellm_kwargs: dict = {}
        self._embedding_dim: int | None = None

    @property
    def is_functional(self) -> bool:
        """Return True if API key is available for embeddings."""
        return self._api_ready

    @property
    def embedding_dim(self) -> int | None:
        """Return the embedding dimension if known."""
        return self._embedding_dim

    async def _load_model(self) -> None:
        """Configure API backend via LiteLLM."""
        if self._api_ready:
            return

        if self._init_lock is None:
            self._init_lock = asyncio.Lock()

        async with self._init_lock:
            if self._api_ready:
                return

            if settings.AI_PROVIDER == "mock":
                logger.info("AI_PROVIDER=mock — embedding service disabled")
                return

            # Use embedding-specific credentials, fall back to LLM credentials
            emb_key = settings.EMBEDDING_API_KEY.get_secret_value()
            api_key = emb_key if emb_key else settings.LLM_API_KEY.get_secret_value()
            if not api_key:
                logger.warning("Embedding service requires an API key. Configure EMBEDDING_API_KEY or LLM_API_KEY.")
                return

            import litellm  # noqa: F401

            emb_base = settings.EMBEDDING_API_BASE_URL
            base_url = emb_base if emb_base else settings.LLM_API_BASE_URL

            if base_url:
                self._litellm_model = f"openai/{self.model_name}"
                self._litellm_kwargs = {"api_base": base_url, "api_key": api_key}
            else:
                self._litellm_model = self.model_name
                self._litellm_kwargs = {"api_key": api_key}

            self._api_ready = True
            logger.info("Embedding service ready: model=%s", self._litellm_model)

    async def embed(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        await self._load_model()

        if not self._api_ready:
            raise RuntimeError("Embedding service requires an API key. Configure EMBEDDING_API_KEY or LLM_API_KEY.")

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
                raise RuntimeError(f"Embedding failed after retry: {e}") from e
        raise RuntimeError("Embedding failed")  # unreachable; satisfies type checker

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        await self._load_model()

        if not self._api_ready:
            raise RuntimeError("Embedding service requires an API key. Configure EMBEDDING_API_KEY or LLM_API_KEY.")

        if not texts:
            return []

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
                raise RuntimeError(f"Batch embedding failed after retry: {e}") from e
        raise RuntimeError("Batch embedding failed")  # unreachable; satisfies type checker
