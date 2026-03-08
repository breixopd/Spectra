"""Unit tests for app.services.ai.embeddings module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ai.embeddings import EmbeddingService


@pytest.fixture
def service():
    """Provide a fresh EmbeddingService."""
    return EmbeddingService(model_name="test-model")


class TestEmbeddingSingleText:
    """Tests for EmbeddingService.embed() via LiteLLM API."""

    @pytest.mark.asyncio
    async def test_embed_returns_list_of_floats(self, service):
        """embed() returns a list of floats when API is configured."""
        fake_response = MagicMock()
        fake_response.data = [{"embedding": [0.1, 0.2, 0.3]}]

        service._api_ready = True
        service._litellm_model = "openai/test-model"
        service._litellm_kwargs = {"api_key": "k"}

        with patch("litellm.aembedding", new_callable=AsyncMock, return_value=fake_response):
            result = await service.embed("hello world")

        assert isinstance(result, list)
        assert all(isinstance(v, float) for v in result)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_embed_calls_litellm_with_correct_args(self, service):
        """embed() passes model and input to litellm.aembedding."""
        fake_response = MagicMock()
        fake_response.data = [{"embedding": [1.0]}]

        service._api_ready = True
        service._litellm_model = "openai/test-model"
        service._litellm_kwargs = {"api_key": "k", "api_base": "http://example.com"}

        with patch("litellm.aembedding", new_callable=AsyncMock, return_value=fake_response) as mock_embed:
            await service.embed("text")

            mock_embed.assert_called_once_with(
                model="openai/test-model",
                input=["text"],
                encoding_format="float",
                api_key="k",
                api_base="http://example.com",
            )


class TestEmbeddingBatch:
    """Tests for EmbeddingService.embed_batch()."""

    @pytest.mark.asyncio
    async def test_embed_batch_returns_list_of_vectors(self, service):
        """embed_batch() returns a list of embedding lists."""
        fake_response = MagicMock()
        fake_response.data = [
            {"embedding": [0.1, 0.2]},
            {"embedding": [0.3, 0.4]},
        ]

        service._api_ready = True
        service._litellm_model = "openai/test-model"
        service._litellm_kwargs = {"api_key": "k"}

        with patch("litellm.aembedding", new_callable=AsyncMock, return_value=fake_response):
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
    async def test_load_model_sets_use_fallback_when_mock_provider(self, service):
        """_load_model sets _use_fallback when AI_PROVIDER=mock."""
        with patch("app.services.ai.embeddings.settings") as mock_settings:
            mock_settings.AI_PROVIDER = "mock"
            mock_settings.EMBEDDING_PROVIDER = ""
            mock_settings.LLM_API_KEY.get_secret_value.return_value = ""
            await service._load_model()
        assert service._use_fallback is True

    @pytest.mark.asyncio
    async def test_load_model_sets_use_fallback_when_no_api_key(self, service):
        """_load_model sets _use_fallback when no API key and no local available."""
        with patch("app.services.ai.embeddings.settings") as mock_settings:
            mock_settings.AI_PROVIDER = "api"
            mock_settings.EMBEDDING_PROVIDER = ""
            mock_settings.LLM_API_KEY.get_secret_value.return_value = ""
            await service._load_model()
        assert service._use_fallback is True

    @pytest.mark.asyncio
    async def test_load_model_configures_api_with_base_url(self, service):
        """_load_model sets up litellm params with custom base URL."""
        with patch("app.services.ai.embeddings.settings") as mock_settings:
            mock_settings.AI_PROVIDER = "api"
            mock_settings.EMBEDDING_PROVIDER = "api"
            mock_settings.LLM_API_KEY.get_secret_value.return_value = "sk-test"
            mock_settings.LLM_API_BASE_URL = "https://api.example.com/v1"
            await service._load_model()
        assert service._api_ready is True
        assert service._litellm_model == "openai/test-model"
        assert service._litellm_kwargs["api_base"] == "https://api.example.com/v1"

    @pytest.mark.asyncio
    async def test_load_model_skips_if_already_ready(self, service):
        """_load_model is a no-op when API is already configured."""
        service._api_ready = True

        await service._load_model()

        assert service._api_ready is True
        assert service._use_fallback is False

    @pytest.mark.asyncio
    async def test_load_model_skips_if_fallback_active(self, service):
        """_load_model is a no-op when _use_fallback is True."""
        service._use_fallback = True

        await service._load_model()

        assert service._api_ready is False

    @pytest.mark.asyncio
    async def test_load_model_explicit_fallback_provider(self, service):
        """_load_model uses fallback when EMBEDDING_PROVIDER=fallback."""
        with patch("app.services.ai.embeddings.settings") as mock_settings:
            mock_settings.EMBEDDING_PROVIDER = "fallback"
            mock_settings.AI_PROVIDER = "api"
            await service._load_model()
        assert service._use_fallback is True

    @pytest.mark.asyncio
    async def test_load_model_local_provider(self, service):
        """_load_model initializes local backend when EMBEDDING_PROVIDER=local."""
        fake_model = MagicMock()
        fake_model.get_sentence_embedding_dimension.return_value = 384
        fake_st_module = MagicMock()
        fake_st_module.SentenceTransformer.return_value = fake_model

        with patch("app.services.ai.embeddings.settings") as mock_settings:
            mock_settings.EMBEDDING_PROVIDER = "local"
            mock_settings.EMBEDDING_MODEL = "all-MiniLM-L6-v2"
            with patch.dict("sys.modules", {"sentence_transformers": fake_st_module}):
                await service._load_model()

        assert service._api_ready is True
        assert service._use_local is True
        assert service._embedding_dim == 384
        assert service._local_model is fake_model

    @pytest.mark.asyncio
    async def test_local_embed_returns_list(self, service):
        """Local embed returns list of floats."""
        import numpy as np
        fake_embedding = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        service._use_local = True
        service._api_ready = True
        service._local_model = MagicMock()
        service._local_model.encode = MagicMock(return_value=fake_embedding)

        result = await service.embed("hello")

        assert isinstance(result, list)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_local_embed_batch_returns_list_of_lists(self, service):
        """Local embed_batch returns list of lists."""
        import numpy as np
        fake_embeddings = np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32)
        service._use_local = True
        service._api_ready = True
        service._local_model = MagicMock()
        service._local_model.encode = MagicMock(return_value=fake_embeddings)

        result = await service.embed_batch(["a", "b"])

        assert len(result) == 2
        assert all(isinstance(row, list) for row in result)

    @pytest.mark.asyncio
    async def test_embedding_dim_property(self, service):
        """embedding_dim returns None when not set, value when set."""
        assert service.embedding_dim is None
        service._embedding_dim = 384
        assert service.embedding_dim == 384

    @pytest.mark.asyncio
    async def test_auto_detect_prefers_local(self, service):
        """Auto-detect mode tries local first."""
        fake_model = MagicMock()
        fake_model.get_sentence_embedding_dimension.return_value = 384
        fake_st_module = MagicMock()
        fake_st_module.SentenceTransformer.return_value = fake_model

        with patch("app.services.ai.embeddings.settings") as mock_settings:
            mock_settings.EMBEDDING_PROVIDER = ""
            mock_settings.AI_PROVIDER = "api"
            mock_settings.EMBEDDING_MODEL = "all-MiniLM-L6-v2"
            with patch.dict("sys.modules", {"sentence_transformers": fake_st_module}):
                await service._load_model()

        assert service._use_local is True
        assert service._api_ready is True

    @pytest.mark.asyncio
    async def test_auto_detect_falls_to_api(self, service):
        """Auto-detect falls to API when local unavailable."""
        with patch("app.services.ai.embeddings.settings") as mock_settings:
            mock_settings.EMBEDDING_PROVIDER = ""
            mock_settings.AI_PROVIDER = "api"
            mock_settings.LLM_API_KEY.get_secret_value.return_value = "sk-test"
            mock_settings.LLM_API_BASE_URL = "https://api.example.com/v1"
            mock_settings.EMBEDDING_MODEL = "text-embedding-3-small"
            # Simulate sentence-transformers not available
            with patch.dict("sys.modules", {"sentence_transformers": None}):
                await service._load_model()

        assert service._use_local is False
        assert service._api_ready is True

    @pytest.mark.asyncio
    async def test_local_model_name_override_for_openai_default(self):
        """When model is text-embedding-3-small, local mode uses all-MiniLM-L6-v2."""
        svc = EmbeddingService(model_name="text-embedding-3-small")
        fake_model = MagicMock()
        fake_model.get_sentence_embedding_dimension.return_value = 384
        fake_st_module = MagicMock()
        fake_st_module.SentenceTransformer.return_value = fake_model

        with patch("app.services.ai.embeddings.settings") as mock_settings:
            mock_settings.EMBEDDING_PROVIDER = "local"
            mock_settings.EMBEDDING_MODEL = "text-embedding-3-small"
            with patch.dict("sys.modules", {"sentence_transformers": fake_st_module}):
                await svc._load_model()
                fake_st_module.SentenceTransformer.assert_called_once_with("all-MiniLM-L6-v2")
