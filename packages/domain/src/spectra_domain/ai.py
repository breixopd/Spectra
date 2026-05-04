"""Contracts for the internal AI service HTTP API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    messages: list[dict[str, Any]]
    model: str | None = None
    tier: int = 2
    temperature: float = 0.7
    max_tokens: int | None = None
    user_id: str | None = None


class ChatResponse(BaseModel):
    content: str
    model: str
    usage: dict[str, Any] = Field(default_factory=dict)


class EmbeddingRequest(BaseModel):
    texts: list[str]
    model: str | None = None
    user_id: str | None = None


class EmbeddingResponse(BaseModel):
    embeddings: list[list[float]]
    model: str
    dimensions: int


class RAGRequest(BaseModel):
    """RAG search payload for the internal AI HTTP API and gateway clients."""

    model_config = ConfigDict(extra="ignore")

    query: str
    collection: str = "default"
    top_k: int = 5
    filters: dict[str, Any] | None = None
    doc_type: str | None = None
    doc_types: list[str] | None = None
    user_id: str | None = None
    exclude_session_id: str | None = None

    def to_search_kwargs(self) -> dict[str, Any]:
        """Arguments for :meth:`spectra_ai.rag.RAGService.search` (monolith or ai-svc)."""
        out: dict[str, Any] = {"top_k": self.top_k, "filters": self.filters}
        if self.doc_type is not None:
            out["doc_type"] = self.doc_type
        if self.doc_types is not None:
            out["doc_types"] = self.doc_types
        if self.user_id is not None:
            out["user_id"] = self.user_id
        if self.exclude_session_id is not None:
            out["exclude_session_id"] = self.exclude_session_id
        return out


class RAGResponse(BaseModel):
    results: list[dict[str, Any]]
    query: str
