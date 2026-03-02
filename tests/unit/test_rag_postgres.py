from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.rag_postgres import PostgresRAGService


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows=None):
        self._rows = rows or []
        self.execute = AsyncMock(return_value=_FakeResult(self._rows))
        self.commit = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_search_returns_ranked_results():
    service = PostgresRAGService()
    service._table_ready = True
    service.config.min_score = 0.5
    service.embeddings = MagicMock()
    service.embeddings.embed = AsyncMock(return_value=[1.0, 0.0])

    rows = [
        {
            "id": "doc-1",
            "content": "match",
            "doc_type": "knowledge",
            "cve_id": None,
            "severity": None,
            "target": None,
            "session_id": None,
            "metadata": {},
            "embedding": [1.0, 0.0],
        },
        {
            "id": "doc-2",
            "content": "non-match",
            "doc_type": "knowledge",
            "cve_id": None,
            "severity": None,
            "target": None,
            "session_id": None,
            "metadata": {},
            "embedding": [0.0, 1.0],
        },
    ]

    with patch("app.services.ai.rag_postgres.async_session_maker", return_value=_FakeSession(rows)):
        results = await service.search("query", top_k=2)

    assert len(results) == 1
    assert results[0].document.id == "doc-1"
    assert results[0].score == pytest.approx(1.0)
    assert all(result.score >= service.config.min_score for result in results)
    assert all(result.document.id != "doc-2" for result in results)


def test_cosine_similarity_handles_zero_vectors():
    assert PostgresRAGService._cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
