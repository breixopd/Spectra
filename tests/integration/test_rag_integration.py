import importlib.util
import os

import pytest
import pytest_asyncio

from app.core.config import settings
from app.services.ai.rag import Document, RAGService

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        "sqlite" in os.environ.get("DATABASE_URL", "sqlite"),
        reason="RAG requires PostgreSQL with pgvector",
    ),
]


def _requires_local_fastembed() -> bool:
    return settings.EMBEDDING_MODEL.lower().startswith("local/") or not settings.EMBEDDING_API_KEY.get_secret_value()


@pytest_asyncio.fixture
async def rag_service():
    """Get an initialized RAG service (PostgreSQL-backed)."""
    if _requires_local_fastembed() and importlib.util.find_spec("fastembed") is None:
        pytest.skip("RAG local embeddings require optional dependency 'fastembed'")

    service = RAGService()
    result = await service.initialize()
    if not result:
        pytest.skip("RAG initialization failed (PostgreSQL/pgvector not available)")
    yield service


@pytest.mark.asyncio
async def test_rag_indexing_and_search(rag_service):
    """Test full RAG flow: Index -> Search -> Retrieve."""

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
async def test_rag_cve_search(rag_service):
    """Test specialized CVE search."""

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
async def test_batch_indexing(rag_service):
    """Test batch indexing."""

    docs = [Document(id=f"batch-{i}", content=f"Batch document number {i}", doc_type="test") for i in range(5)]

    count = await rag_service.index_batch(docs)
    assert count == 5

    # Verify retrieval
    doc = await rag_service.get_document("batch-0")
    assert doc is not None


@pytest.mark.asyncio
async def test_delete_document(rag_service):
    """Test document deletion."""
    doc = Document(id="del-1", content="Delete me", doc_type="temp")
    await rag_service.index_document(doc)
    await rag_service.delete_document("del-1")
    assert await rag_service.get_document("del-1") is None
