"""Unit tests for the AI service entrypoints."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from tests.helpers import make_module


@pytest.mark.asyncio
async def test_lifespan_initializes_embeddings_on_startup():
    from app import ai_service

    embedding_service = SimpleNamespace(_load_model=AsyncMock())

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.services.ai.embeddings",
            make_module("app.services.ai.embeddings", EmbeddingService=lambda: embedding_service),
        )

        async with ai_service.lifespan(ai_service.app):
            pass

    embedding_service._load_model.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_tolerates_embedding_init_failure():
    from app import ai_service

    embedding_service = SimpleNamespace(_load_model=AsyncMock(side_effect=OSError("model missing")))

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.services.ai.embeddings",
            make_module("app.services.ai.embeddings", EmbeddingService=lambda: embedding_service),
        )

        async with ai_service.lifespan(ai_service.app):
            pass

    embedding_service._load_model.assert_awaited_once()


@pytest.mark.asyncio
async def test_health_returns_ai_service_status():
    from unittest.mock import AsyncMock, patch

    from app import ai_service

    mock_response = SimpleNamespace(status_code=200)
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=SimpleNamespace(get=AsyncMock(return_value=mock_response)))
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await ai_service.health()

    assert result["service"] == "ai"
    assert result["status"] == "healthy"
    assert result["tensorzero"] == "reachable"


@pytest.mark.asyncio
async def test_ai_chat_returns_router_response():
    from app import ai_service

    router = SimpleNamespace(
        generate=AsyncMock(return_value=SimpleNamespace(content="planned", model="gpt-test", usage={"tokens": 42}))
    )
    request = ai_service.ChatRequest(
        messages=[
            {"role": "system", "content": "be precise"},
            {"role": "user", "content": "scan target"},
        ],
        tier=3,
        temperature=0.2,
        max_tokens=256,
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.services.ai.router",
            make_module("app.services.ai.router", get_smart_router=lambda: router),
        )
        response = await ai_service.ai_chat(request)

    assert response.content == "planned"
    assert response.model == "gpt-test"
    assert response.usage == {"tokens": 42}
    assert router.generate.await_args.kwargs == {
        "prompt": "scan target",
        "system_prompt": "be precise",
        "temperature": 0.2,
        "max_tokens": 256,
        "task_type": "exploit_crafting",
    }


@pytest.mark.asyncio
async def test_ai_chat_wraps_router_failures():
    from app import ai_service

    router = SimpleNamespace(generate=AsyncMock(side_effect=TimeoutError("timeout")))

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.services.ai.router",
            make_module("app.services.ai.router", get_smart_router=lambda: router),
        )
        with pytest.raises(HTTPException) as exc:
            await ai_service.ai_chat(ai_service.ChatRequest(messages=[{"role": "user", "content": "ping"}]))

    assert exc.value.status_code == 500
    assert exc.value.detail == "Internal service error"


@pytest.mark.asyncio
async def test_generate_embeddings_returns_vectors_and_dimensions():
    from app import ai_service

    embedding_service = SimpleNamespace(
        model_name="mini-embed",
        _load_model=AsyncMock(),
        embed_batch=AsyncMock(return_value=[[0.1, 0.2], [0.3, 0.4]]),
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.services.ai.embeddings",
            make_module("app.services.ai.embeddings", EmbeddingService=lambda model_name="": embedding_service),
        )
        response = await ai_service.generate_embeddings(
            ai_service.EmbeddingRequest(texts=["alpha", "beta"], model="mini-embed")
        )

    assert response.embeddings == [[0.1, 0.2], [0.3, 0.4]]
    assert response.model == "mini-embed"
    assert response.dimensions == 2
    embedding_service._load_model.assert_awaited_once()
    embedding_service.embed_batch.assert_awaited_once_with(["alpha", "beta"])


@pytest.mark.asyncio
async def test_generate_embeddings_wraps_service_failures():
    from app import ai_service

    embedding_service = SimpleNamespace(_load_model=AsyncMock(side_effect=RuntimeError("boom")))

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.services.ai.embeddings",
            make_module("app.services.ai.embeddings", EmbeddingService=lambda model_name="": embedding_service),
        )
        with pytest.raises(HTTPException) as exc:
            await ai_service.generate_embeddings(ai_service.EmbeddingRequest(texts=["alpha"]))

    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_rag_query_returns_serialized_results():
    from app import ai_service

    results = [
        SimpleNamespace(
            document=SimpleNamespace(content="doc-1", metadata={"source": "kb"}),
            score=0.91,
        )
    ]
    rag_service = SimpleNamespace(search=AsyncMock(return_value=results))

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.services.ai.rag",
            make_module("app.services.ai.rag", RAGService=lambda: rag_service),
        )
        response = await ai_service.rag_query(
            ai_service.RAGRequest(query="what changed", top_k=3, filters={"kind": "doc"})
        )

    assert response.query == "what changed"
    assert response.results == [{"content": "doc-1", "score": 0.91, "metadata": {"source": "kb"}}]
    rag_service.search.assert_awaited_once_with(query="what changed", top_k=3, filters={"kind": "doc"})


@pytest.mark.asyncio
async def test_rag_query_wraps_service_failures():
    from app import ai_service

    rag_service = SimpleNamespace(search=AsyncMock(side_effect=ValueError("bad query")))

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.services.ai.rag",
            make_module("app.services.ai.rag", RAGService=lambda: rag_service),
        )
        with pytest.raises(HTTPException) as exc:
            await ai_service.rag_query(ai_service.RAGRequest(query="what changed"))

    assert exc.value.status_code == 500
