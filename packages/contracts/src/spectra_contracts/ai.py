"""AI port interfaces — LLMPort, EmbeddingPort, RagPort."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMPort(Protocol):
    """Port interface for LLM services."""

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float | None = None,
        task_type: str | None = None,
    ) -> Any: ...

    async def health_check(self) -> bool: ...


@runtime_checkable
class EmbeddingPort(Protocol):
    """Port interface for embedding services."""

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_one(self, text: str) -> list[float]: ...


@runtime_checkable
class RagPort(Protocol):
    """Port interface for RAG services."""

    @property
    def is_functional(self) -> bool: ...

    async def search(
        self,
        query: str,
        doc_types: list[str] | None = None,
        top_k: int = 5,
        filters: dict[str, str] | None = None,
    ) -> list[Any]: ...
