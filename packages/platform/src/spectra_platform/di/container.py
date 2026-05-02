"""Lightweight dependency injection container for service instantiation.

Provides factory functions that can be used as FastAPI dependencies.
All services should be obtained through this module rather than
direct instantiation to enable testing and configuration flexibility.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from spectra_platform.core.database import async_session_maker

logger = logging.getLogger(__name__)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a scoped database session for request lifetime."""
    async with async_session_maker() as session:
        try:
            yield session
        except (OSError, RuntimeError):
            await session.rollback()
            raise
        finally:
            await session.close()


@functools.lru_cache(maxsize=1)
def get_job_queue():
    """Return the singleton job queue instance."""
    from spectra_platform.infrastructure.queue import PostgresJobQueue

    return PostgresJobQueue()


@functools.lru_cache(maxsize=1)
def get_tool_registry():
    """Return the singleton tool registry."""
    from spectra_platform.services.tools.registry import ToolRegistry

    return ToolRegistry()


def get_gateway_client(base_url: str, *, api_key: str = ""):
    """Return a gateway HTTP client for the given base URL."""
    from spectra_platform.services.gateway.http_client import GatewayClient

    return GatewayClient(base_url, api_key=api_key)


@functools.lru_cache(maxsize=1)
def get_sandbox_pool():
    """Return the singleton sandbox pool."""
    from spectra_platform.services.tools.sandbox.pool import SandboxPool

    return SandboxPool()


def get_storage_service():
    """Return a new storage service instance."""
    from spectra_platform.services.storage.service import StorageService

    return StorageService()
