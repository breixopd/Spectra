import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.ai.rag import RAGService, Document, RAGConfig
from app.services.ai.embeddings import EmbeddingService


@pytest.fixture
def mock_redis():
    mock = AsyncMock()
    # ft() is synchronous component accessor in redis-py (usually),
    # returns a Search client which has async methods.

    search_client = MagicMock()
    search_client.info = AsyncMock()
    search_client.create_index = AsyncMock()
    search_client.search = AsyncMock()

    # We replace the auto-created AsyncMock with a MagicMock
    mock.ft = MagicMock(return_value=search_client)

    return mock


@pytest.fixture
def mock_embedding_service():
    with patch("app.services.ai.rag.EmbeddingService") as MockService:
        service = MockService.return_value
        service.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])
        service.embed_batch = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
        yield service


@pytest.mark.asyncio
async def test_rag_initialization(mock_redis, mock_embedding_service):
    """Test that RAG service initializes correctly."""
    with patch("app.services.ai.rag.logger") as mock_logger:
        rag = RAGService(mock_redis)
        rag.embeddings = mock_embedding_service

        # Mock index info check raising error (index doesn't exist)
        from redis.exceptions import ResponseError

        mock_redis.ft.return_value.info.side_effect = ResponseError("Unknown index")

        # Needs to return a value for create_index
        mock_redis.ft.return_value.create_index.return_value = "OK"

        success = await rag.initialize()

        if not success:
            error_logs = [c for c in mock_logger.method_calls if "error" in str(c)]
            assert False, f"Initialize failed. Errors: {error_logs}"

        assert success is True
        mock_redis.ft.return_value.create_index.assert_called_once()


@pytest.mark.asyncio
async def test_index_document(mock_redis, mock_embedding_service):
    """Test indexing a document."""
    with patch("app.services.ai.rag.logger") as mock_logger:
        rag = RAGService(mock_redis)
        rag.embeddings = mock_embedding_service
        rag._index_exists = True

        doc = Document(id="test-1", content="Test content", doc_type="knowledge")

        # Mock hset
        mock_redis.hset.return_value = 1

        success = await rag.index_document(doc)

        if not success:
            error_logs = [c for c in mock_logger.method_calls if "error" in str(c)]
            assert False, f"Index failed. Errors: {error_logs}"

        assert success is True
        mock_redis.hset.assert_called_once()
        mock_embedding_service.embed.assert_called_once_with("Test content")


@pytest.mark.asyncio
async def test_search(mock_redis, mock_embedding_service):
    """Test searching."""
    rag = RAGService(mock_redis)
    rag.embeddings = mock_embedding_service
    rag._index_exists = True

    # Mock search result
    mock_doc = MagicMock()
    # Redis client returns bytes usually, but library might decode if configured.
    # RAGService expects standard objects from result.docs
    mock_doc.id = "spectra:rag:doc:test-1"
    mock_doc.content = "Test content"
    mock_doc.doc_type = "knowledge"
    mock_doc.score = 0.1
    # Mock attributes access (some might be missing in real objects if not returned)
    mock_doc.cve_id = None
    mock_doc.severity = None
    mock_doc.target = None
    mock_doc.session_id = None
    mock_doc.metadata = "{}"

    mock_result = MagicMock()
    mock_result.docs = [mock_doc]

    mock_redis.ft.return_value.search.return_value = mock_result

    results = await rag.search("query")

    assert len(results) == 1
    assert results[0].document.content == "Test content"
    mock_embedding_service.embed.assert_called_with("query")


@pytest.mark.asyncio
async def test_embedding_service_loading():
    """Test EmbeddingService produces embeddings (uses fallback if sentence-transformers unavailable)."""
    service = EmbeddingService()
    embedding = await service.embed("test")

    # Should return a list of floats with consistent dimensionality
    assert isinstance(embedding, list)
    assert len(embedding) > 0
    assert all(isinstance(x, float) for x in embedding)

    # Same input should produce same output (deterministic)
    embedding2 = await service.embed("test")
    assert embedding == embedding2
