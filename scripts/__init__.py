"""
Scripts package.

Shared utilities for command-line scripts.
"""

from redis.asyncio import Redis

from app.core.config import settings
from app.services.ai.rag import RAGService
from app.services.tools.registry import get_registry


async def init_script_services() -> tuple[Redis, RAGService]:
    """
    Initialize common services for scripts.

    Returns:
        Tuple of (redis_client, rag_service)
    """
    redis = Redis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )

    rag = RAGService(redis)
    await rag.initialize()

    return redis, rag


__all__ = ["init_script_services", "get_registry"]
