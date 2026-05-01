"""Tests for AIGateway monolith (no AI_SERVICE_URL) fallbacks."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.gateway import ai_gateway as ag


@pytest.fixture(autouse=True)
def reset_ai_gateway_singleton():
    ag._instance = None
    yield
    ag._instance = None


@pytest.mark.asyncio
async def test_rag_search_monolith_uses_get_rag_service(monkeypatch):
    mock_rag = MagicMock()
    mock_rag.search = AsyncMock(return_value=[])

    async def fake_get_rag():
        return mock_rag

    monkeypatch.setattr(ag.settings, "AI_SERVICE_URL", "")
    monkeypatch.setattr("app.services.ai.knowledge.get_rag_service", fake_get_rag)

    gw = ag.AIGateway()
    assert gw.client is None

    await gw.rag_search("probe", top_k=3, filters={"k": "v"}, doc_types=["finding"], user_id="u-1")

    mock_rag.search.assert_awaited_once()
    call_kw = mock_rag.search.call_args.kwargs
    assert call_kw["query"] == "probe"
    assert call_kw["top_k"] == 3
    assert call_kw["filters"] == {"k": "v"}
    assert call_kw["doc_types"] == ["finding"]
    assert call_kw["user_id"] == "u-1"


@pytest.mark.asyncio
async def test_check_embeddings_monolith_uses_get_rag_service(monkeypatch):
    mock_rag = MagicMock()
    mock_rag.is_functional = True

    async def fake_get_rag():
        return mock_rag

    monkeypatch.setattr(ag.settings, "AI_SERVICE_URL", "")
    monkeypatch.setattr("app.services.ai.knowledge.get_rag_service", fake_get_rag)

    gw = ag.AIGateway()
    status = await gw.check_embeddings_status()

    assert status["functional"] is True
    assert status["status"] == "healthy"
