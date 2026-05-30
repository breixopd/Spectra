"""Persistence port interfaces — UnitOfWork and repository ports."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class UnitOfWork(Protocol):
    """Unit of work pattern for database transactions."""

    async def __aenter__(self) -> Any: ...
    async def __aexit__(self, *args: Any) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
