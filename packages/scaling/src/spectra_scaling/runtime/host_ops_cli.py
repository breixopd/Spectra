"""One-shot host/pool maintenance: Docker prune via the same helpers as the scheduler.

Invoked on bare-metal pool nodes from systemd/cron:

    docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \\
      <registry>/spectra-scheduler:<tag> python -m spectra_scaling.runtime.host_ops_cli
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

logger = logging.getLogger("spectra.host_ops")


async def run_docker_prune_round(*, include_managed_volumes: bool = False) -> int:
    """Prune safe Docker resources; volumes require an explicit opt-in."""
    if not Path("/var/run/docker.sock").exists():
        logger.info("host_ops: no /var/run/docker.sock — skipping Docker prune")
        return 0
    try:
        from spectra_scaling.docker_client import (
            prune_containers,
            prune_images,
            prune_volumes,
        )

        managed_filter = {"label": ["spectra.managed=true"]}
        await prune_containers(filters={**managed_filter, "until": ["48h"]})
        await prune_images(filters={**managed_filter, "dangling": ["true"], "until": ["168h"]})
        if include_managed_volumes:
            await prune_volumes(filters={"label": ["spectra.managed=true"]})
        await prune_containers(
            filters={
                # Swarm task containers do not inherit the image's managed
                # label. Scope this exceptional cleanup to Spectra's stack
                # namespace instead of retaining task debris indefinitely.
                "label": ["com.docker.stack.namespace=spectra", "com.docker.swarm.task"],
                "status": ["exited"],
                "until": ["168h"],
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
    parser.add_argument(
        "--prune-managed-volumes",
        action="store_true",
        help="Prune only unused volumes labelled spectra.managed=true.",
    )
    args = parser.parse_args(argv)
    return asyncio.run(run_docker_prune_round(include_managed_volumes=args.prune_managed_volumes))


if __name__ == "__main__":
    sys.exit(main())
