"""Unit tests for app.services.ai.embeddings module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

import numpy as np

from app.services.ai.embeddings import EmbeddingService


@pytest.fixture
def service():
    """Provide a fresh EmbeddingService."""
    return EmbeddingService(model_name="test-model")


class TestEmbeddingSingleText:
    """Tests for EmbeddingService.embed()."""

    @pytest.mark.asyncio
    async def test_embed_returns_list_of_floats(self, service):
        """embed() returns a list of floats when model is loaded."""
        fake_vector = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        mock_model = MagicMock()
        mock_model.encode.return_value = fake_vector

        with patch(
            "app.services.ai.embeddings.SentenceTransformer",
            return_value=mock_model,
            create=True,
        ):
            service._model = mock_model

            result = await service.embed("hello world")

        assert isinstance(result, list)
        assert all(isinstance(v, float) for v in result)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_embed_calls_encode_with_normalize(self, service):
        """embed() passes normalize_embeddings=True to model.encode."""
        fake_vector = np.array([1.0], dtype=np.float32)
        mock_model = MagicMock()
        mock_model.encode.return_value = fake_vector
        service._model = mock_model

        await service.embed("text")

        mock_model.encode.assert_called_once()
        _, kwargs = mock_model.encode.call_args
        assert kwargs.get("normalize_embeddings") is True


class TestEmbeddingBatch:
    """Tests for EmbeddingService.embed_batch()."""

    @pytest.mark.asyncio
    async def test_embed_batch_returns_list_of_vectors(self, service):
        """embed_batch() returns a list of embedding lists."""
        fake_matrix = np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32)
        mock_model = MagicMock()
        mock_model.encode.return_value = fake_matrix
        service._model = mock_model

        result = await service.embed_batch(["a", "b"])

        assert len(result) == 2
        assert all(isinstance(row, list) for row in result)
        assert all(isinstance(v, float) for v in result[0])


class TestFallbackEmbedding:
    """Tests for fallback embedding when sentence-transformers is unavailable."""

    @pytest.mark.asyncio
    async def test_fallback_on_import_error(self, service):
        """embed() falls back gracefully when sentence-transformers is missing."""
        service._use_fallback = True

        result = await service.embed("test input")

        assert isinstance(result, list)
        assert len(result) == 384

    @pytest.mark.asyncio
    async def test_fallback_returns_normalised_vector(self, service):
        """Fallback vectors have approximately unit magnitude."""
        service._use_fallback = True

        vec = await service.embed("some text")

        magnitude = sum(v * v for v in vec) ** 0.5
        assert abs(magnitude - 1.0) < 1e-5

    @pytest.mark.asyncio
    async def test_fallback_deterministic(self, service):
        """Same text always produces the same fallback embedding."""
        service._use_fallback = True

        v1 = await service.embed("deterministic")
        v2 = await service.embed("deterministic")

        assert v1 == v2


class TestModelLoading:
    """Tests for _load_model() lazy-loading behaviour."""

    @pytest.mark.asyncio
    async def test_load_model_sets_use_fallback_on_import_error(self, service):
        """_load_model sets _use_fallback when import fails."""
        with patch.dict("sys.modules", {"sentence_transformers": None}):
            await service._load_model()

        assert service._use_fallback is True

    @pytest.mark.asyncio
    async def test_load_model_skips_if_already_loaded(self, service):
        """_load_model is a no-op when model is already set."""
        service._model = MagicMock()

        await service._load_model()

        assert service._model is not None
        assert service._use_fallback is False

    @pytest.mark.asyncio
    async def test_load_model_skips_if_fallback_active(self, service):
        """_load_model is a no-op when _use_fallback is True."""
        service._use_fallback = True

        await service._load_model()

        assert service._model is None
