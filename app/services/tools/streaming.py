"""Live tool output streaming via Redis pub/sub.

This module enables real-time streaming of tool output so that WebSocket
clients can display stdout/stderr as it is produced, rather than waiting
for the full command to complete.

Architecture
------------
1. The **tools worker** (``app/worker.py``) publishes each line of stdout via
   ``publish_tool_output`` to a Redis pub/sub channel.
2. The **app container** subscribes with ``subscribe_tool_output`` and
   forwards messages to connected WebSocket clients.

Enabling streaming in the worker
---------------------------------
``worker.py`` runs in a separate container and is intentionally not modified
by this module.  To enable streaming, change ``_run_command`` in
``app/worker.py`` to read stdout line-by-line instead of using
``proc.communicate()``:

.. code-block:: python

    from app.services.tools.streaming import publish_tool_output

    async def _run_command(command, timeout, cwd=None, *, redis=None,
                           mission_id="", tool_id=""):
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd, env=env, start_new_session=True,
        )
        lines = []
        async for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace")
            lines.append(line)
            if redis:
                await publish_tool_output(redis, mission_id, tool_id, line)
        stderr_bytes = await proc.stderr.read()
        await proc.wait()
        return (proc.returncode or 0,
                "".join(lines),
                stderr_bytes.decode("utf-8", errors="replace"))

The ``redis`` handle is available as ``ctx["redis"]`` inside every ARQ job
function, so it can simply be passed through.
"""

import json
import logging
from typing import Any, Callable, Awaitable

logger = logging.getLogger("spectra.tools.streaming")

STREAM_CHANNEL = "spectra:tool_output"


async def publish_tool_output(
    redis_client: Any, mission_id: str, tool_id: str, line: str
) -> None:
    """Publish a line of tool output to Redis pub/sub."""
    message = json.dumps(
        {
            "mission_id": mission_id,
            "tool_id": tool_id,
            "line": line,
            "type": "tool_output",
        }
    )
    try:
        await redis_client.publish(STREAM_CHANNEL, message)
    except Exception as e:
        logger.debug("Failed to publish tool output: %s", e)


async def subscribe_tool_output(
    redis_client: Any,
    callback: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    """Subscribe to tool output stream and call *callback* for each message."""
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(STREAM_CHANNEL)
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    await callback(data)
                except Exception as e:
                    logger.debug("Failed to decode tool output: %s", e)
    finally:
        await pubsub.unsubscribe(STREAM_CHANNEL)
