"""RAGFacade — domain-level wrapper around the core RAGService.

Provides typed helpers for storing and searching mission findings, CVEs,
tool documentation, and other knowledge artifacts.
"""

from __future__ import annotations

import logging
from typing import Any

from spectra_ai_core.rag import RAGService

logger = logging.getLogger(__name__)

_rag_facade: RAGFacade | None = None


class RAGFacade:
    """High-level facade for RAG operations used by platform services."""

    def __init__(self, rag_service: RAGService | None = None) -> None:
        self._rag: RAGService = rag_service or RAGService()

    @property
    def is_functional(self) -> bool:
        return self._rag.is_functional

    async def store_mission_finding(
        self,
        finding_id: str,
        content: str,
        target: str,
        severity: str = "medium",
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> bool:
        from spectra_ai_core.rag import Document

        doc = Document(
            id=f"finding:{finding_id}",
            content=content,
            doc_type="finding",
            target=target,
            severity=severity,
            session_id=session_id,
        )
        return await self._rag.index_document(doc)

    async def store_cve(self, cve_id: str, content: str, severity: str = "medium") -> bool:
        from spectra_ai_core.rag import Document

        doc = Document(
            id=f"cve:{cve_id}",
            content=content,
            doc_type="cve",
            cve_id=cve_id,
            severity=severity,
        )
        return await self._rag.index_document(doc)

    async def search_findings(
        self,
        query: str,
        target: str | None = None,
        top_k: int = 5,
    ) -> list[Any]:
        filters: dict[str, str] = {"doc_type": "finding"}
        if target:
            filters["target"] = target
        return await self._rag.search(query, doc_types=["finding"], top_k=top_k, filters=filters)

    async def search_cves(self, query: str, top_k: int = 5) -> list[Any]:
        return await self._rag.search(query, doc_types=["cve"], top_k=top_k)

    async def get_context_for_prompt(
        self,
        query: str,
        doc_types: list[str] | None = None,
        top_k: int = 3,
        max_chars: int = 2000,
    ) -> str:
        return await self._rag.get_context_for_prompt(
            query=query,
            doc_types=doc_types,
            # The core RAG service controls retrieval breadth itself and
            # exposes a token budget rather than a character limit.
            max_tokens=max(1, max_chars // self._rag.CHARS_PER_TOKEN),
        )

    async def index_document(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        id: str | None = None,
        doc_type: str = "knowledge",
    ) -> bool:
        import uuid

        from spectra_ai_core.rag import Document

        doc = Document(
            id=id or f"doc-{uuid.uuid4().hex[:8]}",
            content=content,
            doc_type=doc_type,
            metadata=metadata or {},
        )
        return await self._rag.index_document(doc)

    async def index_tool_output(
        self,
        mission_id: str,
        tool_name: str,
        output: str,
        target: str | None = None,
        max_chars: int = 50000,
    ) -> bool:
        if not output:
            return False
        from spectra_ai_core.rag import Document

        content = f"Tool output from {tool_name}:\n{output[:max_chars]}"
        doc = Document(
            id=f"tool-{mission_id}-{tool_name}",
            content=content,
            doc_type="tool_output",
            target=target,
            session_id=mission_id,
        )
        return await self._rag.index_document(doc)

    async def index_finding(
        self,
        finding: dict[str, Any],
        mission_id: str | None = None,
    ) -> bool:
        import uuid

        from spectra_ai_core.rag import Document

        name = finding.get("name") or "unknown"
        description = finding.get("description") or ""
        tool = finding.get("tool") or "unknown"
        host = finding.get("host") or ""
        severity = finding.get("severity") or "medium"

        content_parts = [f"Finding: {name}"]
        if host:
            content_parts.append(f"Host: {host}")
        content_parts.append(f"Tool: {tool}")
        if description:
            content_parts.append(description)
        content = "\n".join(content_parts)

        doc = Document(
            id=f"finding-{uuid.uuid4().hex[:8]}",
            content=content,
            doc_type="finding",
            severity=severity,
            session_id=mission_id,
        )
        return await self._rag.index_document(doc)

    async def search(
        self,
        query: str,
        limit: int = 5,
        doc_type: str | None = None,
    ) -> list[Any]:
        if doc_type:
            return await self._rag.search(query, top_k=limit, doc_type=doc_type)
        return await self._rag.search(query, top_k=limit)


def get_rag_facade() -> RAGFacade:
    """Get the global RAGFacade singleton."""
    global _rag_facade
    if _rag_facade is None:
        _rag_facade = RAGFacade()
    return _rag_facade
