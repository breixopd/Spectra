"""Spectra Worker Service — handles tool execution from the job queue."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.tasks import create_safe_task

logger = logging.getLogger(__name__)

_worker_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start worker loops on startup."""
    global _worker_task
    logger.info("Worker service starting...")
    _worker_task = create_safe_task(work_loop(), name="worker_loop")
    yield
    logger.info("Worker service shutting down...")
    if _worker_task:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Spectra Worker", version="1.0.0", lifespan=lifespan)

# Service auth middleware (applied after app creation)
from app.core.config import get_settings
from app.core.service_auth import ServiceAuthMiddleware

_settings = get_settings()
_secret = _settings.SERVICE_AUTH_SECRET.get_secret_value()
if _secret:
    app.add_middleware(ServiceAuthMiddleware, secret=_secret)


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "worker",
        "task_alive": _worker_task is not None and not _worker_task.done(),
    }


async def work_loop():
    """Pull and execute tool jobs from the PG queue using the existing worker infrastructure."""
    from app.core.queue import worker_loop
    from app.worker import _WORKER_FUNCTIONS
    from app.worker.lifecycle import shutdown, startup

    queue_name = os.environ.get("QUEUE_NAME", "default")

    await startup()
    try:
        await worker_loop(_WORKER_FUNCTIONS, queue_name=queue_name)
    finally:
        await shutdown()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8003)
