"""Unit tests for spectra_domain AI contracts."""

import pytest
from pydantic import ValidationError

from spectra_domain.ai import ChatRequest, EmbeddingRequest, RAGRequest


def test_rag_request_to_search_kwargs_minimal():
    r = RAGRequest(query="hello")
    assert r.to_search_kwargs() == {"top_k": 5, "filters": None}


def test_rag_request_to_search_kwargs_scoped():
    r = RAGRequest(
        query="q",
        top_k=7,
        filters={"a": "b"},
        doc_types=["finding"],
        user_id="u1",
        exclude_session_id="mid",
    )
    assert r.to_search_kwargs() == {
        "top_k": 7,
        "filters": {"a": "b"},
        "doc_types": ["finding"],
        "user_id": "u1",
        "exclude_session_id": "mid",
    }


def test_rag_request_ignores_unknown_payload_keys():
    r = RAGRequest.model_validate({"query": "z", "unknown": 1})
    assert r.query == "z"
    assert r.to_search_kwargs() == {"top_k": 5, "filters": None}


def test_ai_request_limits_prevent_unbounded_work():
    with pytest.raises(ValidationError):
        RAGRequest(query="hello", top_k=101)
    with pytest.raises(ValidationError):
        EmbeddingRequest(texts=[])
    with pytest.raises(ValidationError):
        ChatRequest(messages=[], tier=4)


def test_chat_request_rejects_oversized_message_budget():
    with pytest.raises(ValidationError, match="message content budget"):
        ChatRequest(messages=[{"role": "user", "content": "x" * 70_000}])
