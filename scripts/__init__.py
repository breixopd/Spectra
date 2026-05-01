"""
Scripts package.

Shared utilities for command-line scripts.

RAG note: ``init_script_services`` constructs :class:`spectra_ai.rag.RAGService`
directly so CLI/one-off processes get a fresh Postgres-backed index without the
API singleton from ``app.services.ai.knowledge.get_rag_service``. The HTTP AI
microservice uses ``RAGService()`` per request in ``spectra_ai.main`` (stateless
workers). The monolith and gateway should prefer ``get_rag_service()`` for a
shared connection pool.
"""

from spectra_platform.services.tools.registry import get_registry
from spectra_ai.rag import RAGService


async def init_script_services() -> RAGService:
    """Initialize common services for scripts.

    Returns:
        Initialized RAGService (Postgres-backed).
    """
    rag = RAGService()
    await rag.initialize()
    return rag


__all__ = ["get_registry", "init_script_services"]
