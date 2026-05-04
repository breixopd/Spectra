"""Unit tests for spectra_domain AI contracts."""

from spectra_domain.ai import RAGRequest


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
