"""Lightweight periodic tasks started inside API, worker, and AI containers.

The scheduler already owns cluster-wide DB/docker/heal loops. This daemon adds
per-container resilience: resource snapshots and optional Docker prune when the
socket is mounted (worker hosts), without duplicating scheduler advisory locks
at high frequency.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

logger = logging.getLogger("spectra.embedded_daemon")


async def embedded_ops_loop(service_label: str, interval_secs: int = 3600) -> None:
    """Run until cancelled: log disk snapshot; prune Docker if socket present (6h+ cadence)."""
    prune_every = max(interval_secs * 6, 21_600)
    last_prune = 0.0
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(interval_secs)
        try:
            du = shutil.disk_usage("/")
            free_gb = round(du.free / (1024**3), 2)
            logger.info(
                "embedded_ops[%s]: disk_free_gb=%s total_gb=%s",
                service_label,
                free_gb,
                round(du.total / (1024**3), 2),
            )
        except OSError as e:
            logger.debug("embedded_ops disk probe failed: %s", e)

        now = loop.time()
        if not Path("/var/run/docker.sock").exists():
            continue
        if now - last_prune < prune_every:
            continue
        try:
            from spectra_scaling.docker_client import (
                prune_containers,
                prune_images,
            )

            await prune_containers(filters={"until": ["72h"]})
            await prune_images(filters={"dangling": ["true"], "until": ["240h"]})
            last_prune = now
            logger.info("embedded_ops[%s]: light docker prune completed", service_label)
        except Exception as e:
            logger.warning("embedded_ops[%s]: prune skipped: %s", service_label, e)


def spawn_embedded_ops_task(service_label: str) -> asyncio.Task[None]:
    """Start background loop; caller must hold task reference until shutdown."""
    from spectra_common.tasks import create_safe_task

    return create_safe_task(embedded_ops_loop(service_label), name=f"embedded_ops_{service_label}")
