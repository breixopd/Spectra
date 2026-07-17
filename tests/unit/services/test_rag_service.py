"""Tests for the RAG service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectra_ai_core.rag import Document, RAGConfig, RAGService, SearchResult


@pytest.fixture
def rag_service():
    with patch("spectra_ai_core.rag.EmbeddingService") as MockEmbed:
        mock_embed = MockEmbed.return_value
        mock_embed.is_functional = False
        mock_embed.embed_one = AsyncMock(return_value=[0.1] * 384)
        mock_embed.embed = AsyncMock(return_value=[[0.1] * 384])
        svc = RAGService()
        yield svc


@pytest.fixture
def functional_rag():
    with patch("spectra_ai_core.rag.EmbeddingService") as MockEmbed:
        mock_embed = MockEmbed.return_value
        mock_embed.is_functional = True
        mock_embed.embed_one = AsyncMock(return_value=[0.5] * 384)
        mock_embed.embed = AsyncMock(return_value=[[0.5] * 384])
        svc = RAGService()
        yield svc


@pytest.fixture
def sample_doc():
    return Document(
        id="doc-001",
        content="SQL injection vulnerability in login form",
        doc_type="finding",
        severity="high",
        target="192.168.1.1",
    )


class TestRAGConfig:
    def test_default_config(self):
        cfg = RAGConfig()
        assert cfg.embedding_dim == 0
        assert cfg.default_top_k == 5
        assert cfg.min_score == 0.5

    def test_custom_config(self):
        cfg = RAGConfig(default_top_k=10, min_score=0.3)
        assert cfg.default_top_k == 10
        assert cfg.min_score == 0.3


class TestRAGServiceInit:
    def test_is_functional_false_with_fallback(self, rag_service):
        assert not rag_service.is_functional

    def test_is_functional_true_with_real_embeddings(self, functional_rag):
        assert functional_rag.is_functional

    def test_default_config_used(self, rag_service):
        assert rag_service.config.embedding_dim == 0


class TestRAGDocument:
    def test_document_creation(self, sample_doc):
        assert sample_doc.id == "doc-001"
        assert sample_doc.doc_type == "finding"
        assert sample_doc.severity == "high"

    def test_document_optional_fields(self):
        doc = Document(id="d1", content="test", doc_type="knowledge")
        assert doc.cve_id is None
        assert doc.severity is None
        assert doc.target is None
        assert doc.session_id is None
        assert doc.metadata == {}


class TestRAGIndexDocument:
    @pytest.mark.asyncio
    async def test_index_document_calls_embed(self, functional_rag, sample_doc):
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session_maker = AsyncMock()
        mock_session_maker.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_maker.__aexit__ = AsyncMock(return_value=False)

        functional_rag._table_ready = True

        with patch("spectra_ai_core.rag.get_async_session_maker", return_value=lambda: mock_session_maker):
            await functional_rag.index_document(sample_doc)
            functional_rag.embeddings.embed_one.assert_awaited_once_with(sample_doc.content)

    @pytest.mark.asyncio
    async def test_index_initializes_if_not_ready(self, rag_service, sample_doc):
        rag_service._table_ready = False
        rag_service.initialize = AsyncMock(return_value=True)

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session_maker = AsyncMock()
        mock_session_maker.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_maker.__aexit__ = AsyncMock(return_value=False)

        with patch("spectra_ai_core.rag.get_async_session_maker", return_value=lambda: mock_session_maker):
            await rag_service.index_document(sample_doc)
            rag_service.initialize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_index_document_handles_error(self, functional_rag, sample_doc):
        functional_rag._table_ready = True
        functional_rag.embeddings.embed_one = AsyncMock(side_effect=RuntimeError("embed fail"))

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=AsyncMock(scalar=MagicMock(return_value=None)))
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("spectra_ai_core.rag.get_async_session_maker", return_value=lambda: mock_cm):
            result = await functional_rag.index_document(sample_doc)
        assert result is False


class TestRAGBatchIndex:
    @pytest.mark.asyncio
    async def test_empty_batch(self, rag_service):
        result = await rag_service.index_batch([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_batch_falls_back_to_sequential(self, rag_service):
        """When batch embedding fails, index_batch falls back to index_document."""
        docs = [
            Document(id="d1", content="test1", doc_type="cve"),
            Document(id="d2", content="test2", doc_type="finding"),
        ]
        rag_service._table_ready = True
        rag_service.embeddings.embed = AsyncMock(side_effect=RuntimeError("batch fail"))
        rag_service.index_document = AsyncMock(return_value=True)

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=AsyncMock(mappings=lambda: AsyncMock(all=list)))
        mock_session_maker = AsyncMock()
        mock_session_maker.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_maker.__aexit__ = AsyncMock(return_value=False)

        with patch("spectra_ai_core.rag.get_async_session_maker", return_value=lambda: mock_session_maker):
            result = await rag_service.index_batch(docs)
        assert result == 2
        assert rag_service.index_document.await_count == 2


class TestSearchResult:
    def test_search_result_model(self):
        doc = Document(id="d1", content="test", doc_type="cve")
        sr = SearchResult(document=doc, score=0.95)
        assert sr.score == 0.95
        assert sr.highlights == []


class TestRAGSearchFilters:
    @pytest.mark.asyncio
    async def test_search_passes_doc_types_user_and_exclude_session(self, functional_rag):
        functional_rag._table_ready = True
        row = {
            "id": "f1",
            "content": "body",
            "doc_type": "finding",
            "cve_id": None,
            "severity": "high",
            "target": "10.0.0.1",
            "session_id": "other-mission",
            "metadata": {},
            "similarity": 0.99,
        }
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [row]
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("spectra_ai_core.rag.get_async_session_maker", return_value=lambda: mock_cm):
            out = await functional_rag.search(
                "query",
                top_k=2,
                doc_types=["finding", "lesson"],
                user_id="user-9",
                exclude_session_id="mission-x",
            )

        assert len(out) == 1
        call_kw = mock_session.execute.call_args_list[-1][0][1]
        assert call_kw["dt_0"] == "finding"
        assert call_kw["dt_1"] == "lesson"
        assert call_kw["rag_user_id"] == "user-9"
        assert call_kw["rag_exclude_session"] == "mission-x"
