"""RAG (Retrieval-Augmented Generation) service package.

Provides convenience wrappers and a high-level facade over ``spectra_ai.rag.RAGService``
for common indexing and search operations.
"""

from spectra_platform.services.rag.service import RAGFacade, get_rag_facade

__all__ = ["RAGFacade", "get_rag_facade"]
