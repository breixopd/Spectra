"""Unit tests for spectra_ai.embeddings module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectra_ai_core.embeddings import EmbeddingService


@pytest.fixture
def service():
    """Provide a fresh EmbeddingService."""
    return EmbeddingService(model_name="test-model")


class TestEmbeddingSingleText:
    """Tests for EmbeddingService.embed() via OpenAI SDK API."""

    @pytest.mark.asyncio
    async def test_embed_returns_list_of_floats(self, service):
        """embed() returns a list of floats when API is configured."""
        mock_client = AsyncMock()
        mock_embedding = MagicMock()
        mock_embedding.embedding = [0.1, 0.2, 0.3]
        mock_response = MagicMock()
        mock_response.data = [mock_embedding]
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        service._api_ready = True
        service._use_local = False
        service._openai_client = mock_client
        service._openai_model = "test-model"

        result = await service.embed_one("hello world")

        assert isinstance(result, list)
        assert all(isinstance(v, float) for v in result)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_embed_calls_openai_with_correct_args(self, service):
        """embed() passes model and input to openai client."""
        mock_client = AsyncMock()
        mock_embedding = MagicMock()
        mock_embedding.embedding = [1.0]
        mock_response = MagicMock()
        mock_response.data = [mock_embedding]
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        service._api_ready = True
        service._use_local = False
        service._openai_client = mock_client
        service._openai_model = "test-model"

        await service.embed_one("text")

        mock_client.embeddings.create.assert_called_once_with(
            model="test-model",
            input=["text"],
            encoding_format="float",
        )


class TestEmbeddingBatch:
    """Tests for EmbeddingService.embed_batch()."""

    @pytest.mark.asyncio
    async def test_embed_batch_returns_list_of_vectors(self, service):
        """embed_batch() returns a list of embedding lists."""
        mock_client = AsyncMock()
        mock_emb1 = MagicMock()
        mock_emb1.embedding = [0.1, 0.2]
        mock_emb2 = MagicMock()
        mock_emb2.embedding = [0.3, 0.4]
        mock_response = MagicMock()
        mock_response.data = [mock_emb1, mock_emb2]
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        service._api_ready = True
        service._use_local = False
        service._openai_client = mock_client
        service._openai_model = "test-model"

        result = await service.embed(["a", "b"])

        assert len(result) == 2
        assert all(isinstance(row, list) for row in result)
        assert all(isinstance(v, float) for v in result[0])


class TestModelLoading:
    """Tests for _load_model() lazy-loading behaviour."""

    @pytest.fixture(autouse=True)
    def _fake_fastembed(self):
        """Stub fastembed so local-model tests are deterministic and avoid the
        real backend's "load once per process" limitation."""
        import sys
        import types

        fake_mod = types.ModuleType("fastembed")

        class _FakeTextEmbedding:
            def __init__(self, *args, **kwargs):
                pass

            def embed(self, texts):
                return [[0.1, 0.2, 0.3] for _ in texts]

        fake_mod.TextEmbedding = _FakeTextEmbedding
        with patch.dict(sys.modules, {"fastembed": fake_mod}):
            yield

    @pytest.mark.asyncio
    async def test_load_model_uses_local_fallback_when_no_api_key(self, service):
        """_load_model falls back to local model when no API key is available."""
        mock_settings = MagicMock()
        mock_settings.EMBEDDING_API_KEY.get_secret_value.return_value = ""
        mock_settings.EMBEDDING_MODEL = "test-model"
        with patch("spectra_ai_core.embeddings.get_ai_settings", return_value=mock_settings):
            await service._load_model()
        assert service._api_ready is True
        assert service._use_local is True

    @pytest.mark.asyncio
    async def test_load_model_uses_local_when_no_api_key(self, service):
        """_load_model configures local fastembed when no API key is available."""
        mock_settings = MagicMock()
        mock_settings.EMBEDDING_API_KEY.get_secret_value.return_value = ""
        mock_settings.EMBEDDING_MODEL = "test-model"
        with patch("spectra_ai_core.embeddings.get_ai_settings", return_value=mock_settings):
            await service._load_model()
        assert service._api_ready is True
        assert service._use_local is True
        assert service._local_model_name == "BAAI/bge-small-en-v1.5"

    @pytest.mark.asyncio
    async def test_load_model_configures_api_with_base_url(self, service):
        """_load_model sets up OpenAI client with custom base URL."""
        mock_settings = MagicMock()
        mock_settings.EMBEDDING_API_KEY.get_secret_value.return_value = "sk-test"
        mock_settings.EMBEDDING_API_BASE_URL = "https://api.example.com/v1"
        mock_settings.EMBEDDING_MODEL = "test-model"
        with (
            patch("spectra_ai_core.embeddings.get_ai_settings", return_value=mock_settings),
            patch("openai.AsyncOpenAI") as mock_openai_cls,
        ):
            await service._load_model()
        assert service._api_ready is True
        assert service._openai_model == "test-model"
        mock_openai_cls.assert_called_once_with(
            api_key="sk-test",
            base_url="https://api.example.com/v1",
        )

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
    async def test_embed_uses_local_fallback_when_no_api_key(self, service):
        """embed() falls back to local embeddings when no API key configured."""
        mock_settings = MagicMock()
        mock_settings.EMBEDDING_API_KEY.get_secret_value.return_value = ""
        mock_settings.EMBEDDING_MODEL = "test-model"
        with patch("spectra_ai_core.embeddings.get_ai_settings", return_value=mock_settings):
            await service._load_model()
        assert service._use_local is True
        assert service._api_ready is True

    @pytest.mark.asyncio
    async def test_embed_batch_uses_local_fallback_when_no_api_key(self, service):
        """embed_batch() falls back to local embeddings when no API key configured."""
        mock_settings = MagicMock()
        mock_settings.EMBEDDING_API_KEY.get_secret_value.return_value = ""
        mock_settings.EMBEDDING_MODEL = "test-model"
        with patch("spectra_ai_core.embeddings.get_ai_settings", return_value=mock_settings):
            await service._load_model()
        assert service._use_local is True
        assert service._api_ready is True

    @pytest.mark.asyncio
    async def test_is_functional_false_without_api_key(self, service):
        """is_functional returns False when not initialized."""
        assert service.is_functional is False

    @pytest.mark.asyncio
    async def test_is_functional_true_after_api_init(self, service):
        """is_functional returns True after successful API init."""
        mock_settings = MagicMock()
        mock_settings.EMBEDDING_API_KEY.get_secret_value.return_value = "sk-test"
        mock_settings.EMBEDDING_API_BASE_URL = ""
        mock_settings.EMBEDDING_MODEL = "test-model"
        with (
            patch("spectra_ai_core.embeddings.get_ai_settings", return_value=mock_settings),
            patch("openai.AsyncOpenAI"),
        ):
            await service._load_model()
        assert service.is_functional is True

    @pytest.mark.asyncio
    async def test_load_model_configures_api_without_base_url(self, service):
        """_load_model creates OpenAI client without base_url when not set."""
        mock_settings = MagicMock()
        mock_settings.EMBEDDING_API_KEY.get_secret_value.return_value = "sk-test"
        mock_settings.EMBEDDING_API_BASE_URL = ""
        mock_settings.EMBEDDING_MODEL = "test-model"
        with (
            patch("spectra_ai_core.embeddings.get_ai_settings", return_value=mock_settings),
            patch("openai.AsyncOpenAI") as mock_openai_cls,
        ):
            await service._load_model()
        assert service._api_ready is True
        assert service._openai_model == "test-model"
        mock_openai_cls.assert_called_once_with(
            api_key="sk-test",
            base_url=None,
        )
