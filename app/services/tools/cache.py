"""Tool result caching.

Caches parsed results from security tool scans to avoid re-running
identical scans within a configurable time window.
"""

import hashlib
import json
import logging
from datetime import timedelta

logger = logging.getLogger("spectra.tools.cache")


class ToolResultCache:
    """Cache for tool execution results.

    Uses the tool name + target + arguments as a composite key.
    Default TTL is 1 hour — same scan against same target won't rerun.
    """

    def __init__(self, default_ttl: timedelta = timedelta(hours=1)):
        self._default_ttl = default_ttl

    def _make_key(self, tool_name: str, target: str, args: dict | None = None) -> str:
        """Create a deterministic cache key from tool + target + args."""
        key_data = json.dumps({"tool": tool_name, "target": target, "args": args or {}}, sort_keys=True)
        return f"tool_cache:{hashlib.sha256(key_data.encode()).hexdigest()[:16]}"

    async def get(self, tool_name: str, target: str, args: dict | None = None) -> dict | None:
        """Get cached result if available and not expired."""
        from sqlalchemy import text

        from app.core.database import async_session_maker

        key = self._make_key(tool_name, target, args)
        try:
            async with async_session_maker() as session:
                result = await session.execute(
                    text("SELECT value FROM system_cache WHERE key = :key AND (expires_at IS NULL OR expires_at > now())"),
                    {"key": key}
                )
                row = result.fetchone()
                if row:
                    data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                    logger.info("Cache HIT: %s on %s", tool_name, target)
                    return data
        except Exception as e:
            logger.debug("Cache lookup failed: %s", e)
        return None

    async def set(self, tool_name: str, target: str, result: dict,
                  args: dict | None = None, ttl: timedelta | None = None):
        """Cache a tool result."""
        from sqlalchemy import text

        from app.core.database import async_session_maker

        key = self._make_key(tool_name, target, args)
        ttl = ttl or self._default_ttl
        ttl_seconds = int(ttl.total_seconds())

        try:
            async with async_session_maker() as session:
                await session.execute(
                    text("""
                        INSERT INTO system_cache (key, value, expires_at)
                        VALUES (:key, :value, now() + make_interval(secs => :ttl))
                        ON CONFLICT (key) DO UPDATE SET value = :value, expires_at = now() + make_interval(secs => :ttl)
                    """),
                    {"key": key, "value": json.dumps(result), "ttl": ttl_seconds}
                )
                await session.commit()
                logger.info("Cache SET: %s on %s (TTL: %ds)", tool_name, target, ttl_seconds)
        except Exception as e:
            logger.debug("Cache set failed: %s", e)

    async def invalidate(self, tool_name: str, target: str, args: dict | None = None):
        """Invalidate a specific cache entry."""
        from sqlalchemy import text

        from app.core.database import async_session_maker

        key = self._make_key(tool_name, target, args)
        try:
            async with async_session_maker() as session:
                await session.execute(text("DELETE FROM system_cache WHERE key = :key"), {"key": key})
                await session.commit()
        except Exception:
            pass


# Singleton
_tool_cache: ToolResultCache | None = None

def get_tool_cache() -> ToolResultCache:
    global _tool_cache
    if _tool_cache is None:
        _tool_cache = ToolResultCache()
    return _tool_cache
