"""Contracts for the internal AI service HTTP API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_CHAT_MESSAGES = 128
MAX_CHAT_CONTENT_CHARS = 64_000
MAX_EMBEDDING_TEXTS = 128
MAX_EMBEDDING_TEXT_CHARS = 32_000


class ChatRequest(BaseModel):
    messages: list[dict[str, Any]] = Field(min_length=1, max_length=MAX_CHAT_MESSAGES)
    model: str | None = None
    tier: int = Field(default=2, ge=1, le=3)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=32_000)
    user_id: str | None = None

    @model_validator(mode="after")
    def validate_message_budget(self) -> ChatRequest:
        """Bound request size before it reaches a model or queue worker."""

        def content_size(value: Any) -> int:
            if isinstance(value, str):
                return len(value)
            if isinstance(value, dict):
                return sum(content_size(item) for item in value.values())
            if isinstance(value, (list, tuple)):
                return sum(content_size(item) for item in value)
            return 0

        total = sum(content_size(message.get("content")) for message in self.messages)
        if total > MAX_CHAT_CONTENT_CHARS:
            raise ValueError(f"message content budget exceeds {MAX_CHAT_CONTENT_CHARS} characters")
        return self


class ChatResponse(BaseModel):
    content: str
    model: str
    usage: dict[str, Any] = Field(default_factory=dict)


class EmbeddingRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=MAX_EMBEDDING_TEXTS)
    model: str | None = None
    user_id: str | None = None

    @field_validator("texts")
    @classmethod
    def validate_text_sizes(cls, texts: list[str]) -> list[str]:
        if any(len(text) > MAX_EMBEDDING_TEXT_CHARS for text in texts):
            raise ValueError(f"embedding text exceeds {MAX_EMBEDDING_TEXT_CHARS} characters")
        return texts


class EmbeddingResponse(BaseModel):
    embeddings: list[list[float]]
    model: str
    dimensions: int


class RAGRequest(BaseModel):
    """RAG search payload for the internal AI HTTP API and gateway clients."""

    model_config = ConfigDict(extra="ignore")

    query: str = Field(min_length=1, max_length=32_000)
    collection: str = "default"
    top_k: int = Field(default=5, ge=1, le=100)
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
