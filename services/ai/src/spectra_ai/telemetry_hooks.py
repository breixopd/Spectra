"""Pluggable LLM telemetry for ``spectra_ai``.

The API/worker process registers ``app.telemetry.telemetry.record_llm_call`` at
import time. The standalone AI image does the same when ``app.telemetry`` is on
the path. Until then, recording is a no-op.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

_record_llm: Callable[..., Awaitable[None]] | None = None


def set_record_llm_call(fn: Callable[..., Awaitable[None]] | None) -> None:
    """Register the platform LLM metrics recorder (or clear with None)."""
    global _record_llm
    _record_llm = fn


async def record_llm_call(
    *,
    provider: str,
    model: str,
    duration_ms: float,
    tokens: int,
    success: bool,
) -> None:
    if _record_llm is None:
        return
    await _record_llm(
        provider=provider,
        model=model,
        duration_ms=duration_ms,
        tokens=tokens,
        success=success,
    )
