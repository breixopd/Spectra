"""Global SmartRouter singleton management.

The concrete TensorZeroRouter is provided by services/ai. This module owns the
singleton reference so bounded packages (mission, tools, etc.) can call
get_smart_router() without importing the deployable service package.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_smart_router: Any | None = None


def set_smart_router(router: Any) -> None:
    """Register the concrete router instance (called by services/ai at startup)."""
    global _smart_router
    _smart_router = router


def get_smart_router() -> Any:
    """Return the global SmartRouter instance.

    Raises RuntimeError if services/ai has not registered a router yet.
    """
    if _smart_router is None:
        raise RuntimeError(
            "No SmartRouter registered. services/ai must call "
            "spectra_ai_core.router.set_smart_router() at startup."
        )
    return _smart_router


async def close_smart_router() -> None:
    """Close and release the global SmartRouter singleton."""
    global _smart_router
    if _smart_router is not None:
        await _smart_router.close()
        _smart_router = None
