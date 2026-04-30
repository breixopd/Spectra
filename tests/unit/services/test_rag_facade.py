"""Tests for the RAG facade service (app.services.rag.service)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.rag.service import RAGFacade, get_rag_facade
from spectra_ai.rag import Document, SearchResult


@pytest.fixture
def mock_rag_service():
    svc = MagicMock()
    svc.is_functional = True
    svc.index_document = AsyncMock(return_value=True)
    svc.search = AsyncMock(return_value=[])
    svc.initialize = AsyncMock(return_value=True)
    return svc


@pytest.fixture
def facade(mock_rag_service):
    f = RAGFacade()
    f._rag = AsyncMock(return_value=mock_rag_service)
    return f


class TestRAGFacadeIndexDocument:
    @pytest.mark.asyncio
    async def test_index_document_basic(self, facade, mock_rag_service):
        result = await facade.index_document("Some vulnerability content", {"key": "value"})
        assert result is True
        mock_rag_service.index_document.assert_called_once()
        doc = mock_rag_service.index_document.call_args[0][0]
        assert doc.content == "Some vulnerability content"
        assert doc.metadata == {"key": "value"}
        assert doc.doc_type == "knowledge"

    @pytest.mark.asyncio
    async def test_index_document_with_explicit_id(self, facade, mock_rag_service):
        result = await facade.index_document("content", id="my-doc-1", doc_type="cve")
        assert result is True
        doc = mock_rag_service.index_document.call_args[0][0]
        assert doc.id == "my-doc-1"
        assert doc.doc_type == "cve"

    @pytest.mark.asyncio
    async def test_index_document_auto_generates_id(self, facade, mock_rag_service):
        await facade.index_document("test content")
        doc = mock_rag_service.index_document.call_args[0][0]
        assert doc.id.startswith("doc-")


class TestRAGFacadeSearch:
    @pytest.mark.asyncio
    async def test_search_delegates_to_rag(self, facade, mock_rag_service):
        mock_rag_service.search.return_value = [
            SearchResult(
                document=Document(id="d1", content="found it", doc_type="finding"),
                score=0.9,
            )
        ]
        results = await facade.search("SQL injection", limit=3)
        assert len(results) == 1
        assert results[0].score == 0.9
        mock_rag_service.search.assert_called_once_with("SQL injection", top_k=3)

    @pytest.mark.asyncio
    async def test_search_with_doc_type(self, facade, mock_rag_service):
        await facade.search("test", limit=5, doc_type="cve")
        mock_rag_service.search.assert_called_once_with("test", top_k=5, doc_type="cve")


class TestRAGFacadeIndexToolOutput:
    @pytest.mark.asyncio
    async def test_index_tool_output_success(self, facade, mock_rag_service):
        result = await facade.index_tool_output(
            mission_id="m-123",
            tool_name="nmap",
            output="PORT STATE SERVICE\n22/tcp open ssh",
            target="10.0.0.1",
        )
        assert result is True
        doc = mock_rag_service.index_document.call_args[0][0]
        assert doc.id == "tool-m-123-nmap"
        assert doc.doc_type == "tool_output"
        assert "nmap" in doc.content
        assert doc.target == "10.0.0.1"
        assert doc.session_id == "m-123"

    @pytest.mark.asyncio
    async def test_index_tool_output_empty_output(self, facade, mock_rag_service):
        result = await facade.index_tool_output(mission_id="m-123", tool_name="nmap", output="")
        assert result is False
        mock_rag_service.index_document.assert_not_called()

    @pytest.mark.asyncio
    async def test_index_tool_output_truncates_large_output(self, facade, mock_rag_service):
        large = "x" * 100_000
        await facade.index_tool_output(mission_id="m-123", tool_name="nmap", output=large)
        doc = mock_rag_service.index_document.call_args[0][0]
        # Content includes "Tool output from nmap: " prefix + truncated data
        assert len(doc.content) <= 50_000 + 50


class TestRAGFacadeIndexFinding:
    @pytest.mark.asyncio
    async def test_index_finding_basic(self, facade, mock_rag_service):
        finding = {
            "name": "SQL Injection",
            "host": "10.0.0.1",
            "tool": "sqlmap",
            "description": "Found SQL injection in login form",
            "severity": "high",
        }
        result = await facade.index_finding(finding, mission_id="m-456")
        assert result is True
        doc = mock_rag_service.index_document.call_args[0][0]
        assert "SQL Injection" in doc.content
        assert doc.doc_type == "finding"
        assert doc.severity == "high"
        assert doc.session_id == "m-456"

    @pytest.mark.asyncio
    async def test_index_finding_without_mission(self, facade, mock_rag_service):
        finding = {"name": "XSS", "tool": "nuclei"}
        result = await facade.index_finding(finding)
        assert result is True
        doc = mock_rag_service.index_document.call_args[0][0]
        assert doc.id.startswith("finding-")
        assert doc.session_id is None

    @pytest.mark.asyncio
    async def test_index_finding_defaults_for_missing_fields(self, facade, mock_rag_service):
        finding = {}
        await facade.index_finding(finding, mission_id="m-789")
        doc = mock_rag_service.index_document.call_args[0][0]
        assert "unknown" in doc.content


class TestGetRagFacade:
    def test_singleton(self):
        import app.services.rag.service as mod

        mod._facade = None  # Reset singleton
        f1 = get_rag_facade()
        f2 = get_rag_facade()
        assert f1 is f2
        mod._facade = None  # Cleanup
