"""Contracts for the internal AI service HTTP API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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
    query: str
    collection: str = "default"
    top_k: int = 5
    filters: dict[str, Any] | None = None


class RAGResponse(BaseModel):
    results: list[dict[str, Any]]
    query: str
