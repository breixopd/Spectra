"""LLM client factory for the spectra_ai service.

The abstract LLMClient, LLMResponse, and global singleton management live in
spectra_ai_core.llm. This module provides the concrete TensorZero-backed factory
and registers it with spectra_ai_core so bounded packages can call
get_global_llm_client() without importing service packages.
"""

from __future__ import annotations

import logging
from typing import Any

from spectra_ai.settings import get_ai_settings
from spectra_ai_core.llm import LLMClient, LLMResponse, register_llm_factory

logger = logging.getLogger(__name__)

__all__ = ["LLMClient", "LLMResponse", "get_default_llm_client", "get_llm_client"]


def get_llm_client(
    provider: str = "tensorzero",
    **kwargs: Any,
) -> LLMClient:
    """Factory: create an LLM client backed by the TensorZero gateway."""
    from spectra_ai.router import TensorZeroRouter

    settings = get_ai_settings()
    gateway_url = kwargs.get("gateway_url") or settings.TENSORZERO_GATEWAY_URL
    return TensorZeroRouter(gateway_url=gateway_url)


def get_default_llm_client() -> LLMClient:
    """Get the LLM client configured in settings."""
    settings = get_ai_settings()
    gateway_url = settings.TENSORZERO_GATEWAY_URL
    if not gateway_url:
        raise ValueError(
            "TENSORZERO_GATEWAY_URL is not configured. "
            "Set it to the TensorZero gateway address (e.g., http://tensorzero:3000)"
        )
    client = get_llm_client(gateway_url=gateway_url)
    logger.info("Using TensorZero smart router (provider=tensorzero)")
    return client


# Register the factory with spectra_ai_core.llm so bounded packages can call
# get_global_llm_client() and get_llm_client() without importing service packages.
register_llm_factory(get_llm_client)
