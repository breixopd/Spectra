"""Bridge for PostgreSQL async sessions used by RAG.

``app.core.database`` registers the SQLAlchemy ``async_session_maker`` when
imported so ``spectra_ai.rag`` can run inside the API, worker, or AI container
without importing ORM models from ``app``.
"""

from __future__ import annotations

from typing import Any

def get_async_session_maker() -> Any:
    """Return the platform's async SQLAlchemy session maker.

    Pulled from ``spectra_persistence`` on demand (ai-core depends on persistence),
    so there is no import-time coupling or global registration step.
    """
    from spectra_persistence.database import async_session_maker

    return async_session_maker
