import pytest
import pytest_asyncio
import asyncio
from app.services.ai.rag import RAGService, Document


@pytest.mark.asyncio
async def test_rag_indexing_and_search():
    """Test full RAG flow: Index -> Search -> Retrieve."""
    rag_service = RAGService()
    await rag_service.initialize()

    doc = Document(
        id="test-doc-1",
        content="The quick brown fox jumps over the lazy dog.",
        doc_type="knowledge",
        metadata={"author": "tester"},
    )

    # Index
    success = await rag_service.index_document(doc)
    assert success

    # Search
    results = await rag_service.search("brown fox", top_k=1)
    assert len(results) >= 1
    assert results[0].document.id == "test-doc-1"
    assert results[0].score > 0.0


@pytest.mark.asyncio
async def test_rag_cve_search():
    """Test specialized CVE search."""
    rag_service = RAGService()
    await rag_service.initialize()

    doc = Document(
        id="cve-2024-0001",
        content="Critical SQL injection vulnerability in Login.",
        doc_type="cve",
        cve_id="CVE-2024-0001",
        severity="critical",
    )

    await rag_service.index_document(doc)

    # Search by query
    results = await rag_service.search_cves("SQL injection")
    assert any(r.document.cve_id == "CVE-2024-0001" for r in results)


@pytest.mark.asyncio
async def test_batch_indexing():
    """Test batch indexing."""
    rag_service = RAGService()
    await rag_service.initialize()

    docs = [
        Document(id=f"batch-{i}", content=f"Batch document number {i}", doc_type="test")
        for i in range(5)
    ]

    count = await rag_service.index_batch(docs)
    assert count == 5

    # Verify retrieval
    doc = await rag_service.get_document("batch-0")
    assert doc is not None


@pytest.mark.asyncio
async def test_delete_document():
    """Test document deletion."""
    rag_service = RAGService()
    await rag_service.initialize()

    doc = Document(id="del-1", content="Delete me", doc_type="temp")
    await rag_service.index_document(doc)
    await rag_service.delete_document("del-1")
    assert await rag_service.get_document("del-1") is None
