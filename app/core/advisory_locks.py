"""Helpers for deterministic PostgreSQL advisory lock IDs and lock ownership."""

from __future__ import annotations

import logging
import hashlib
import inspect
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_MAX_SIGNED_BIGINT = (1 << 63) - 1
logger = logging.getLogger(__name__)


def stable_lock_id(name: str) -> int:
    """Return a deterministic positive bigint-safe advisory lock ID."""
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False) & _MAX_SIGNED_BIGINT


@asynccontextmanager
async def advisory_lock_owner(
    lock_id: int,
    *,
    connection_factory: Callable[[], AbstractAsyncContextManager[AsyncConnection]],
) -> AsyncIterator[AsyncConnection | None]:
    """Yield a dedicated autocommit connection owning an advisory lock for the full context block."""
    async with connection_factory() as connection:
        result = await connection.execute(text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": lock_id})
        acquired = result.scalar()
        if inspect.isawaitable(acquired):
            acquired = await acquired
        if not bool(acquired):
            yield None
            return

        try:
            yield connection
        finally:
            try:
                result = await connection.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": lock_id})
                unlocked = result.scalar()
                if inspect.isawaitable(unlocked):
                    unlocked = await unlocked
                if not bool(unlocked):
                    logger.warning("Advisory lock %s was already released before unlock", lock_id)
            except Exception:
                logger.exception("Failed to release advisory lock %s", lock_id)
