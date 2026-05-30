"""Pluggable LLM telemetry for ``spectra_ai``.

The API/worker process registers ``app.telemetry.telemetry.record_llm_call`` at
import time. The standalone AI image does the same when ``app.telemetry`` is on
the path. Until then, recording is a no-op.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

async def record_llm_call(
    *,
    provider: str,
    model: str,
    duration_ms: float,
    tokens: int,
    success: bool,
) -> None:
    """Record an LLM call's metrics via observability, if available.

    Pulls the recorder from ``spectra_observability`` on demand so the standalone
    AI image degrades to a no-op when observability is not installed.
    """
    try:
        from spectra_observability.telemetry import record_llm_call as _obs_record
    except Exception:
        return
    await _obs_record(
        provider=provider,
        model=model,
        duration_ms=duration_ms,
        tokens=tokens,
        success=success,
    )
