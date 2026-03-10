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


class TestModelLoading:
    """Tests for _load_model() lazy-loading behaviour."""

    @pytest.mark.asyncio
    async def test_load_model_no_op_when_mock_provider(self, service):
        """_load_model does not set _api_ready when AI_PROVIDER=mock."""
        with patch("app.services.ai.embeddings.settings") as mock_settings:
            mock_settings.AI_PROVIDER = "mock"
            mock_settings.LLM_API_KEY.get_secret_value.return_value = ""
            await service._load_model()
        assert service._api_ready is False

    @pytest.mark.asyncio
    async def test_load_model_no_op_when_no_api_key(self, service):
        """_load_model does not set _api_ready when no API key."""
        with patch("app.services.ai.embeddings.settings") as mock_settings:
            mock_settings.AI_PROVIDER = "litellm"
            mock_settings.LLM_API_KEY.get_secret_value.return_value = ""
            await service._load_model()
        assert service._api_ready is False

    @pytest.mark.asyncio
    async def test_load_model_configures_api_with_base_url(self, service):
        """_load_model sets up litellm params with custom base URL."""
        with patch("app.services.ai.embeddings.settings") as mock_settings:
            mock_settings.AI_PROVIDER = "litellm"
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

    @pytest.mark.asyncio
    async def test_embedding_dim_property(self, service):
        """embedding_dim returns None when not set, value when set."""
        assert service.embedding_dim is None
        service._embedding_dim = 384
        assert service.embedding_dim == 384

    @pytest.mark.asyncio
    async def test_embed_raises_when_no_api_key(self, service):
        """embed() raises RuntimeError when no API key configured."""
        with patch("app.services.ai.embeddings.settings") as mock_settings:
            mock_settings.AI_PROVIDER = "litellm"
            mock_settings.LLM_API_KEY.get_secret_value.return_value = ""
            with pytest.raises(RuntimeError, match="requires an AI API key"):
                await service.embed("test")

    @pytest.mark.asyncio
    async def test_embed_batch_raises_when_no_api_key(self, service):
        """embed_batch() raises RuntimeError when no API key configured."""
        with patch("app.services.ai.embeddings.settings") as mock_settings:
            mock_settings.AI_PROVIDER = "litellm"
            mock_settings.LLM_API_KEY.get_secret_value.return_value = ""
            with pytest.raises(RuntimeError, match="requires an AI API key"):
                await service.embed_batch(["test"])

    @pytest.mark.asyncio
    async def test_is_functional_false_without_api_key(self, service):
        """is_functional returns False when not initialized."""
        assert service.is_functional is False

    @pytest.mark.asyncio
    async def test_is_functional_true_after_api_init(self, service):
        """is_functional returns True after successful API init."""
        with patch("app.services.ai.embeddings.settings") as mock_settings:
            mock_settings.AI_PROVIDER = "litellm"
            mock_settings.LLM_API_KEY.get_secret_value.return_value = "sk-test"
            mock_settings.LLM_API_BASE_URL = None
            await service._load_model()
        assert service.is_functional is True

    @pytest.mark.asyncio
    async def test_load_model_configures_api_without_base_url(self, service):
        """_load_model uses model name directly when no base URL."""
        with patch("app.services.ai.embeddings.settings") as mock_settings:
            mock_settings.AI_PROVIDER = "litellm"
            mock_settings.LLM_API_KEY.get_secret_value.return_value = "sk-test"
            mock_settings.LLM_API_BASE_URL = None
            await service._load_model()
        assert service._api_ready is True
        assert service._litellm_model == "test-model"
        assert "api_base" not in service._litellm_kwargs
