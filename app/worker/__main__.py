"""Spectra Worker Service — handles tool execution from the job queue."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.infrastructure.tasks import create_safe_task
from app.services.shell.session_manager import shell_manager

logger = logging.getLogger(__name__)

_worker_task: asyncio.Task | None = None
_heartbeat_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start worker loops on startup."""
    global _worker_task, _heartbeat_task
    logger.info("Worker service starting...")
    _worker_task = create_safe_task(work_loop(), name="worker_loop")
    _heartbeat_task = create_safe_task(_run_heartbeat(), name="heartbeat_loop")
    yield
    logger.info("Worker service shutting down...")
    if _heartbeat_task:
        _heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await _heartbeat_task
    if _worker_task:
        _worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await _worker_task


app = FastAPI(title="Spectra Worker", version="1.0.0", lifespan=lifespan)

# Service auth middleware (applied after app creation)
from app.core.config import get_settings
from app.di.service_auth import ServiceAuthMiddleware

_settings = get_settings()
_secret = _settings.SERVICE_AUTH_SECRET.get_secret_value()
if _secret:
    app.add_middleware(ServiceAuthMiddleware, secret=_secret)


@app.get("/health")
async def health():
    status = {
        "status": "healthy",
        "service": "worker",
        "task_alive": _worker_task is not None and not _worker_task.done(),
    }
    try:
        from sqlalchemy import text

        from app.core.database import async_session_maker

        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
        status["database"] = "connected"
    except Exception:
        status["database"] = "disconnected"
        status["status"] = "degraded"
    return status


class ListenerCreateRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    target: str = Field(min_length=1, max_length=255)
    mission_id: str | None = Field(default=None, max_length=128)
    port: int = Field(default=0, ge=0, le=65535)
    ttl_seconds: int = Field(default=900, ge=60, le=3600)


@app.post("/internal/shell/listeners")
async def internal_start_shell_listener(request: ListenerCreateRequest) -> dict[str, int | str | None]:
    """Start a callback listener on the worker data plane."""
    try:
        port = shell_manager.start_listener(
            session_id=request.session_id,
            target=request.target,
            mission_id=request.mission_id,
            port=request.port,
            ttl_seconds=request.ttl_seconds,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"session_id": request.session_id, "mission_id": request.mission_id, "port": port}


@app.get("/internal/shell/listeners")
async def internal_list_shell_listeners() -> list[dict]:
    """List callback listeners owned by this worker."""
    return shell_manager.list_listeners()


@app.delete("/internal/shell/listeners/{session_id}", status_code=204)
async def internal_stop_shell_listener(session_id: str) -> None:
    """Stop a callback listener owned by this worker."""
    if not shell_manager.stop_listener(session_id=session_id):
        raise HTTPException(status_code=404, detail="Listener not found")


async def _run_heartbeat():
    """Run the heartbeat loop so the scheduler can detect stale workers."""
    from app.worker.lifecycle import heartbeat_loop

    queue_name = os.environ.get("QUEUE_NAME", "default")
    await heartbeat_loop(queue_name)


async def work_loop():
    """Pull and execute tool jobs from the PG queue using the existing worker infrastructure."""
    from app.infrastructure.queue import worker_loop
    from app.worker import _WORKER_FUNCTIONS
    from app.worker.lifecycle import shutdown, startup

    queue_name = os.environ.get("QUEUE_NAME", "default")

    await startup()
    try:
        while True:
            try:
                await worker_loop(_WORKER_FUNCTIONS, queue_name=queue_name)
                break  # Normal exit (e.g. cancelled)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Work loop crashed unexpectedly, restarting in 5s")
                await asyncio.sleep(5)
    finally:
        await shutdown()


if __name__ == "__main__":  # pragma: no cover — unreachable during import-based unit tests; starts uvicorn server
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8003)
