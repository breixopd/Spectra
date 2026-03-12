"""RAG (Retrieval-Augmented Generation) service package.

Provides convenience wrappers around the core RAG engine in
``app.services.ai.rag`` for common indexing and search operations.
"""

from app.services.rag.service import RAGFacade, get_rag_facade

__all__ = ["RAGFacade", "get_rag_facade"]
