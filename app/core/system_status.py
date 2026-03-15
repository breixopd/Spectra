"""System status helpers for cache-backed UI status tracking.

Extracted from lifespan.py for reuse and testability.
"""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


async def set_system_status(status: str, message: str) -> None:
    """Update system status in cache for UI polling."""
    try:
        from app.core.cache import get_cache

        cache = get_cache()
        if cache:
            await cache.set("spectra:system:status", {
                "status": status,
                "message": message,
                "timestamp": datetime.now().isoformat(),
            }, ttl=3600)
    except (OSError, RuntimeError) as e:
        logger.debug("Failed to set system status: %s", e)


async def add_system_operation(op_id: str, op_type: str, desc: str) -> None:
    """Add an ongoing operation to the system status."""
    try:
        from app.core.cache import get_cache

        cache = get_cache()
        if cache:
            op = {
                "id": op_id,
                "type": op_type,
                "description": desc,
                "started_at": datetime.now().isoformat(),
            }
            await cache.set(f"spectra:system:operations:{op_id}", op, ttl=3600)
    except (OSError, RuntimeError) as e:
        logger.debug("Failed to add system operation: %s", e)


async def remove_system_operation(op_id: str) -> None:
    """Remove a completed operation."""
    try:
        from app.core.cache import get_cache

        cache = get_cache()
        if cache:
            await cache.delete(f"spectra:system:operations:{op_id}")
    except (OSError, RuntimeError) as e:
        logger.debug("Failed to remove system operation: %s", e)
