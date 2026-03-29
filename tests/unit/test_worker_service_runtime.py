"""Unit tests for the worker service runtime wrapper."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers import make_module


class _AwaitableTask:
    def __init__(self, exc: BaseException | None = None):
        self._exc = exc
        self.cancel = MagicMock()
        self._done = False

    def done(self):
        return self._done

    def __await__(self):
        async def _inner():
            self._done = True
            if self._exc is not None:
                raise self._exc
            return None

        return _inner().__await__()


@pytest.mark.asyncio
async def test_lifespan_starts_and_cancels_worker_task():
    from app import worker_service

    task = _AwaitableTask(exc=asyncio.CancelledError())

    def fake_create_task(coro):
        coro.close()
        return task

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(worker_service.asyncio, "create_task", fake_create_task)
        async with worker_service.lifespan(worker_service.app):
            assert worker_service._worker_task is task

    task.cancel.assert_called_once()


@pytest.mark.asyncio
async def test_health_reports_worker_task_state():
    from app import worker_service

    task = MagicMock()
    task.done.return_value = False
    worker_service._worker_task = task

    assert await worker_service.health() == {
        "status": "healthy",
        "service": "worker",
        "task_alive": True,
    }


@pytest.mark.asyncio
async def test_work_loop_calls_startup_worker_loop_and_shutdown_in_finally():
    from app import worker_service

    order: list[str] = []
    startup = AsyncMock(side_effect=lambda: order.append("startup"))
    shutdown = AsyncMock(side_effect=lambda: order.append("shutdown"))

    async def fake_worker_loop(functions, queue_name):
        order.append(f"worker:{queue_name}:{sorted(functions)}")
        raise RuntimeError("stop")

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.core.queue",
            make_module("app.core.queue", worker_loop=fake_worker_loop),
        )
        mp.setitem(
            sys.modules,
            "app.worker",
            make_module("app.worker", _WORKER_FUNCTIONS={"alpha": object()}),
        )
        mp.setitem(
            sys.modules,
            "app.worker.lifecycle",
            make_module("app.worker.lifecycle", startup=startup, shutdown=shutdown),
        )
        mp.setenv("QUEUE_NAME", "priority")
        with pytest.raises(RuntimeError, match="stop"):
            await worker_service.work_loop()

    assert order == ["startup", "worker:priority:['alpha']", "shutdown"]
    startup.assert_awaited_once()
    shutdown.assert_awaited_once()
