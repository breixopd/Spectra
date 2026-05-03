"""One-shot host/pool maintenance: Docker prune via the same helpers as the scheduler.

Invoked on bare-metal pool nodes from systemd/cron:

    docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \\
      <registry>/spectra-scheduler:<tag> python -m spectra_platform.runtime.host_ops_cli
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

logger = logging.getLogger("spectra.host_ops")


async def run_docker_prune_round() -> int:
    """Prune exited containers, dangling images, and orphaned volumes (best-effort)."""
    if not Path("/var/run/docker.sock").exists():
        logger.info("host_ops: no /var/run/docker.sock — skipping Docker prune")
        return 0
    try:
        from spectra_platform.services.scaling.docker_client import (
            prune_containers,
            prune_images,
            prune_volumes,
        )

        await prune_containers(filters={"until": ["48h"]})
        await prune_images(filters={"until": ["168h"]})
        await prune_volumes()
        await prune_containers(
            filters={
                "label": ["com.docker.swarm.task"],
                "status": ["exited"],
            },
        )
        logger.info("host_ops: docker prune round completed")
    except Exception as e:
        logger.exception("host_ops: docker prune failed: %s", e)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    parser = argparse.ArgumentParser(description="Spectra pool host Docker maintenance (one-shot).")
    parser.parse_args(argv)
    return asyncio.run(run_docker_prune_round())


if __name__ == "__main__":
    sys.exit(main())
