"""
Architecture optimizations for production performance.

1. ARQ connection pooling
2. Lazy model loading
3. Tool result caching
4. Prompt token budgeting
5. Graceful degradation
"""

import asyncio
import hashlib
import json
import logging
import time
from typing import Any

logger = logging.getLogger("spectra.core.optimizations")


# --- 1. ARQ Connection Pool ---

_arq_pool = None
_arq_pool_lock = asyncio.Lock()


async def get_arq_pool():
    """Get or create a shared ARQ Redis pool (reused across requests)."""
    global _arq_pool
    if _arq_pool is not None:
        return _arq_pool

    async with _arq_pool_lock:
        if _arq_pool is not None:
            return _arq_pool

        from arq import create_pool
        from arq.connections import RedisSettings

        from app.core.config import settings
        from app.core.constants import ARQ_QUEUE_NAME

        _arq_pool = await create_pool(
            RedisSettings(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                password=settings.REDIS_PASSWORD.get_secret_value(),
                database=settings.REDIS_DB,
            ),
            default_queue_name=ARQ_QUEUE_NAME,
        )
        return _arq_pool


async def close_arq_pool():
    """Close the shared ARQ pool."""
    global _arq_pool
    if _arq_pool:
        await _arq_pool.close()
        _arq_pool = None


# --- 2. Lazy Model Loading ---


class LazyLoader:
    """Lazy-loads expensive resources only when first accessed."""

    def __init__(self):
        self._loaded = {}

    def get(self, key: str, factory):
        """Get a lazily-loaded resource."""
        if key not in self._loaded:
            self._loaded[key] = factory()
        return self._loaded[key]

    def clear(self, key: str | None = None):
        if key:
            self._loaded.pop(key, None)
        else:
            self._loaded.clear()


lazy = LazyLoader()


# --- 3. Tool Result Cache ---


class ToolResultCache:
    """Cache recent tool results to avoid duplicate scans."""

    def __init__(self, ttl_seconds: int = 300):
        self.ttl = ttl_seconds
        self._cache: dict[str, tuple[float, Any]] = {}

    def _key(self, tool_id: str, target: str, args: dict) -> str:
        raw = f"{tool_id}:{target}:{json.dumps(args, sort_keys=True)}"
        return hashlib.md5(raw.encode()).hexdigest()

    def get(self, tool_id: str, target: str, args: dict) -> Any | None:
        key = self._key(tool_id, target, args)
        if key in self._cache:
            ts, result = self._cache[key]
            if time.time() - ts < self.ttl:
                logger.debug("Cache hit for %s against %s", tool_id, target)
                return result
            del self._cache[key]
        return None

    def set(self, tool_id: str, target: str, args: dict, result: Any) -> None:
        key = self._key(tool_id, target, args)
        self._cache[key] = (time.time(), result)

    def clear(self):
        self._cache.clear()

    @property
    def size(self) -> int:
        return len(self._cache)


tool_cache = ToolResultCache()


# --- 4. Prompt Token Budget ---


class TokenBudget:
    """Track token usage per mission to avoid exceeding limits."""

    def __init__(self, max_tokens: int = 500_000):
        self.max_tokens = max_tokens
        self._usage: dict[str, int] = {}

    def record(self, mission_id: str, tokens: int) -> None:
        self._usage[mission_id] = self._usage.get(mission_id, 0) + tokens

    def get_usage(self, mission_id: str) -> int:
        return self._usage.get(mission_id, 0)

    def get_remaining(self, mission_id: str) -> int:
        return max(0, self.max_tokens - self.get_usage(mission_id))

    def is_over_budget(self, mission_id: str) -> bool:
        return self.get_usage(mission_id) >= self.max_tokens

    def clear(self, mission_id: str | None = None):
        if mission_id:
            self._usage.pop(mission_id, None)
        else:
            self._usage.clear()


token_budget = TokenBudget()


# --- 5. Graceful Degradation ---


async def check_llm_health() -> bool:
    """Check if the LLM provider is reachable."""
    try:
        from app.services.ai.llm import get_global_llm_client

        client = await get_global_llm_client()
        return await client.health_check()
    except Exception:
        return False


async def get_execution_mode() -> str:
    """Determine current execution mode based on LLM availability."""
    if await check_llm_health():
        return "full"
    else:
        return "playbook"
