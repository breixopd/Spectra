"""Runtime AI configuration — TensorZero gateway settings."""

import logging
from typing import Any

from spectra_platform.core.config import settings

logger = logging.getLogger(__name__)


def get_current_ai_config() -> dict[str, Any]:
    """Return the current AI gateway configuration."""
    return {
        "gateway_url": settings.TENSORZERO_GATEWAY_URL,
        "embedding_model": settings.EMBEDDING_MODEL,
        "timeout": settings.LLM_TIMEOUT,
    }


async def apply_ai_settings(rows: dict[str, Any], target_settings: Any) -> dict[str, tuple[str, bool]]:
    """Apply AI-related settings from admin/setup. Returns {key: (value, changed)}."""
    values: dict[str, tuple[str, bool]] = {}

    gw = rows.get("TENSORZERO_GATEWAY_URL", "")
    if gw and gw != getattr(target_settings, "TENSORZERO_GATEWAY_URL", ""):
        values["TENSORZERO_GATEWAY_URL"] = (str(gw), False)

    api_key = rows.get("TENSORZERO_API_KEY", "")
    if api_key:
        values["TENSORZERO_API_KEY"] = (str(api_key), True)

    emb = rows.get("EMBEDDING_MODEL", "")
    if emb and emb != getattr(target_settings, "EMBEDDING_MODEL", ""):
        values["EMBEDDING_MODEL"] = (str(emb), False)

    timeout = rows.get("LLM_TIMEOUT", "")
    if timeout:
        values["LLM_TIMEOUT"] = (str(timeout), False)

    return values
