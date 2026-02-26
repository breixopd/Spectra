"""
Embedding Service.

Handles text embedding generation using local transformer models or fallbacks.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging

import struct

logger = logging.getLogger("spectra.ai.embeddings")


class EmbeddingService:
    """
    Service for generating text embeddings.

    Uses sentence-transformers for local embedding generation.
    Falls back to simple TF-IDF-like vectors if unavailable.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None
        self._use_fallback = False
        self._load_lock: asyncio.Lock | None = None

    async def _load_model(self):
        """Lazy-load the embedding model."""
        if self._model is not None or self._use_fallback:
            return

        # Initialize lock lazily to avoid issues with event loop
        if self._load_lock is None:
            self._load_lock = asyncio.Lock()

        async with self._load_lock:
            # Double-check after acquiring lock
            if self._model is not None or self._use_fallback:
                return

            try:
                from sentence_transformers import SentenceTransformer  # type: ignore

                # Load model in thread pool to avoid blocking the event loop
                loop = asyncio.get_running_loop()
                self._model = await loop.run_in_executor(
                    None, lambda: SentenceTransformer(self.model_name)
                )
                logger.info("Loaded embedding model: %s", self.model_name)
            except ImportError:
                logger.warning(
                    "sentence-transformers not available, using fallback embeddings"
                )
                self._use_fallback = True
            except Exception as e:
                logger.warning("Failed to load embedding model: %s. Using fallback.", e)
                self._use_fallback = True

    async def embed(self, text: str) -> list[float]:
        """Generate embedding for text."""
        await self._load_model()

        if self._use_fallback:
            return self._fallback_embed(text)

        # Use sentence-transformers in a thread pool to avoid blocking
        loop = asyncio.get_running_loop()
        embedding = await loop.run_in_executor(
            None,
            lambda: self._model.encode(text, normalize_embeddings=True),  # type: ignore
        )
        return embedding.tolist()

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        await self._load_model()

        if self._use_fallback:
            return [self._fallback_embed(t) for t in texts]

        # Use sentence-transformers in a thread pool
        loop = asyncio.get_running_loop()
        embeddings = await loop.run_in_executor(
            None,
            lambda: self._model.encode(texts, normalize_embeddings=True),  # type: ignore
        )
        return embeddings.tolist()

    def _fallback_embed(self, text: str, dim: int = 384) -> list[float]:
        """
        Simple fallback embedding using character hashing.
        Not as good as transformer embeddings but works without dependencies.
        """
        # Create a deterministic pseudo-random vector from text hash
        text_hash = hashlib.sha256(text.lower().encode()).digest()

        # Extend hash to cover full dimension
        extended = text_hash
        while len(extended) < dim * 4:
            extended += hashlib.sha256(extended).digest()

        # Convert to floats
        floats = []
        for i in range(dim):
            val = struct.unpack("f", extended[i * 4 : (i + 1) * 4])[0]
            # Normalize to reasonable range
            floats.append(max(-1.0, min(1.0, val / 1e38)))

        # Normalize vector
        magnitude = sum(f * f for f in floats) ** 0.5
        if magnitude > 0:
            floats = [f / magnitude for f in floats]

        return floats
