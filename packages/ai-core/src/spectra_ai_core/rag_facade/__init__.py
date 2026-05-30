"""RAG Facade — higher-level interface for platform-level RAG operations."""

from spectra_ai_core.rag_facade.service import RAGFacade, get_rag_facade

__all__ = ["RAGFacade", "get_rag_facade"]
