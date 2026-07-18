"""In-memory time-series metrics store with periodic snapshots."""

import asyncio
import contextlib
import logging
import time
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)


class MetricsStore:
    """Stores periodic metric snapshots for trending/dashboards."""

    def __init__(self, max_history: int = 1440, interval_seconds: int = 60):
        self._history: deque[dict[str, Any]] = deque(maxlen=max_history)
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start periodic snapshotting."""
        if self._task is not None and not self._task.done():
            return
        from spectra_common.tasks import create_safe_task

        self._task = create_safe_task(self._snapshot_loop(), name="metrics_snapshot")
        logger.info(
            "MetricsStore started (interval=%ds, max_history=%d)",
            self._interval,
            self._history.maxlen,
        )

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _snapshot_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._interval)
                self._take_snapshot()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error taking metrics snapshot")

    def _take_snapshot(self) -> None:
        from spectra_observability.telemetry import telemetry

        overview = telemetry.get_overview_stats()
        snapshot: dict[str, Any] = {
            "_timestamp": time.time(),
            "request_count": overview.get("total_requests", 0),
            "error_count": overview.get("total_errors", 0),
            "error_rate": overview.get("error_rate_percent", 0),
            "avg_latency_ms": overview.get("avg_latency_ms", 0),
            "p50_ms": overview.get("latency_percentiles", {}).get("p50_ms", 0),
            "p90_ms": overview.get("latency_percentiles", {}).get("p90_ms", 0),
            "p99_ms": overview.get("latency_percentiles", {}).get("p99_ms", 0),
            "active_services": overview.get("active_services", 0),
            "healthy_services": overview.get("healthy_services", 0),
        }
        self._history.append(snapshot)

    async def collect(self) -> None:
        """Take a metrics snapshot on demand (used by scheduler service)."""
        self._take_snapshot()

    def get_history(self, minutes: int = 60) -> list[dict[str, Any]]:
        cutoff = time.time() - (minutes * 60)
        return [s for s in self._history if s.get("_timestamp", 0) >= cutoff]

    def get_latest(self) -> dict[str, Any] | None:
        return self._history[-1] if self._history else None


_store: MetricsStore | None = None


def get_metrics_store() -> MetricsStore:
    global _store
    if _store is None:
        _store = MetricsStore()
    return _store
