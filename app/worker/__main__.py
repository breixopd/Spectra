"""Worker entry point: python -m app.worker"""

from __future__ import annotations

import asyncio
import os

from app.worker import _WORKER_FUNCTIONS, heartbeat_loop, shutdown, startup


async def _main() -> None:
    await startup()
    queue_name = os.environ.get("QUEUE_NAME", "default")
    heartbeat_interval = int(os.environ.get("SANDBOX_HEARTBEAT_INTERVAL", "30"))
    heartbeat_task = None

    from app.core.queue import worker_loop

    try:
        if queue_name != "default":
            heartbeat_task = asyncio.create_task(
                heartbeat_loop(queue_name, interval=heartbeat_interval)
            )
        await worker_loop(_WORKER_FUNCTIONS, queue_name=queue_name)
    finally:
        if heartbeat_task:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
        await shutdown()


if __name__ == "__main__":
    asyncio.run(_main())
