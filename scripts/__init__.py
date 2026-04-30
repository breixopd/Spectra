"""
Scripts package.

Shared utilities for command-line scripts.
"""

from app.services.ai.rag import RAGService
from app.services.tools.registry import get_registry


async def init_script_services() -> RAGService:
    """Initialize common services for scripts.

    Returns:
        Initialized RAGService (Postgres-backed).
    """
    rag = RAGService()
    await rag.initialize()
    return rag


__all__ = ["get_registry", "init_script_services"]
