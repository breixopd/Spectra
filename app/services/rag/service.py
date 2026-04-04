"""RAG Facade Service.

High-level convenience methods for indexing and searching documents,
built on top of the core ``app.services.ai.rag.RAGService``.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.ai.knowledge import get_rag_service
from app.services.ai.rag import Document, SearchResult

logger = logging.getLogger(__name__)


class RAGFacade:
    """Convenience wrapper around the core RAG engine."""

    async def _rag(self):
        return await get_rag_service()

    async def index_document(self, content: str, metadata: dict[str, Any] | None = None, **kwargs: Any) -> bool:
        """Embed and store a document.

        Args:
            content: Document text content.
            metadata: Optional metadata dict.
            **kwargs: Extra fields forwarded to ``Document`` (id, doc_type, etc.).

        Returns:
            True if indexing succeeded.
        """
        doc_id = kwargs.pop("id", None) or kwargs.pop("doc_id", None)
        if not doc_id:
            import hashlib

            doc_id = f"doc-{hashlib.sha256(content[:256].encode()).hexdigest()[:12]}"

        doc_type = kwargs.pop("doc_type", "knowledge")
        doc = Document(
            id=doc_id,
            content=content,
            doc_type=doc_type,
            metadata=metadata or {},
            **kwargs,
        )
        rag = await self._rag()
        return await rag.index_document(doc)

    async def search(self, query: str, limit: int = 5, **kwargs: Any) -> list[SearchResult]:
        """Search for relevant documents.

        Args:
            query: Natural language search query.
            limit: Maximum number of results.
            **kwargs: Forwarded to ``RAGService.search`` (doc_type, filters).

        Returns:
            List of search results with scores.
        """
        rag = await self._rag()
        return await rag.search(query, top_k=limit, **kwargs)

    async def index_tool_output(
        self,
        mission_id: str,
        tool_name: str,
        output: str,
        *,
        target: str | None = None,
    ) -> bool:
        """Index a tool's scan output for later retrieval.

        Args:
            mission_id: The mission this output belongs to.
            tool_name: Name of the security tool (e.g. 'nmap', 'nuclei').
            output: Raw or parsed tool output text.
            target: Optional target identifier.

        Returns:
            True if indexing succeeded.
        """
        if not output or not output.strip():
            return False

        # Truncate very large outputs
        max_len = 50_000
        content = output[:max_len] if len(output) > max_len else output

        doc = Document(
            id=f"tool-{mission_id}-{tool_name}",
            content=f"Tool output from {tool_name}: {content}",
            doc_type="tool_output",
            target=target,
            session_id=mission_id,
            metadata={"tool": tool_name, "mission_id": mission_id},
        )
        rag = await self._rag()
        return await rag.index_document(doc)

    async def index_finding(
        self,
        finding: dict[str, Any],
        *,
        mission_id: str | None = None,
    ) -> bool:
        """Index a vulnerability finding for later retrieval.

        Args:
            finding: Finding dict with keys like name, description, severity, host, tool.
            mission_id: Optional mission ID for scoping.

        Returns:
            True if indexing succeeded.
        """
        name = finding.get("name", "unknown")
        host = finding.get("host", "unknown")
        tool = finding.get("tool", "unknown")
        description = finding.get("description", "")
        severity = finding.get("severity")

        content = f"Found {name} on {host} using {tool}. {description}"

        import hashlib

        finding_hash = hashlib.sha256(content[:256].encode()).hexdigest()[:12]
        doc_id = f"finding-{finding_hash}"
        if mission_id:
            doc_id = f"finding-{mission_id}-{finding_hash}"

        doc = Document(
            id=doc_id,
            content=content,
            doc_type="finding",
            severity=severity,
            target=host if host != "unknown" else None,
            session_id=mission_id,
            metadata={
                "tool": tool,
                "template_id": finding.get("template-id"),
            },
        )
        rag = await self._rag()
        return await rag.index_document(doc)


# Singleton
_facade: RAGFacade | None = None


def get_rag_facade() -> RAGFacade:
    """Return the module-level RAGFacade singleton."""
    global _facade
    if _facade is None:
        _facade = RAGFacade()
    return _facade
