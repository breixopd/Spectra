"""Bridge for PostgreSQL async sessions used by RAG.

``app.core.database`` registers the SQLAlchemy ``async_session_maker`` when
imported so ``spectra_ai.rag`` can run inside the API, worker, or AI container
without importing ORM models from ``app``.
"""

from __future__ import annotations

from typing import Any

_async_session_maker: Any | None = None


def set_async_session_maker(maker: Any) -> None:
    global _async_session_maker
    _async_session_maker = maker


def get_async_session_maker() -> Any:
    if _async_session_maker is None:
        msg = (
            "spectra_ai RAG requires an async SQLAlchemy session maker. "
            "Import app.core.database (or call spectra_ai.db.set_async_session_maker) before using RAGService."
        )
        raise RuntimeError(msg)
    return _async_session_maker
