"""Safe asyncio task creation with error logging."""

import asyncio
import logging
from inspect import isawaitable

logger = logging.getLogger(__name__)


def create_safe_task(
    coro,
    *,
    name: str | None = None,
    logger_: logging.Logger | None = None,
) -> asyncio.Task:
    """Create an asyncio task that logs exceptions instead of swallowing them."""
    task = asyncio.create_task(coro, name=name)
    if not hasattr(task, "add_done_callback"):
        if isawaitable(task):
            task.close()
        if isawaitable(coro):
            coro.close()
        return task

    def _done_callback(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            log = logger_ or logger
            log.error("Background task %s failed: %s", t.get_name(), exc, exc_info=exc)

    callback_result = task.add_done_callback(_done_callback)
    if isawaitable(callback_result):
        callback_result.close()
    if not isinstance(task, asyncio.Task) and isawaitable(coro):
        coro.close()
    return task
