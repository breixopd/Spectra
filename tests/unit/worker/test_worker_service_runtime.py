"""Unit tests for the worker service runtime wrapper."""

from __future__ import annotations

import asyncio
import sys
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
    from app.worker import __main__ as worker_service

    task = _AwaitableTask(exc=asyncio.CancelledError())

    def fake_create_safe_task(coro, *, name=None, logger_=None):
        coro.close()
        return task

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(worker_service, "create_safe_task", fake_create_safe_task)
        async with worker_service.lifespan(worker_service.app):
            assert worker_service._worker_task is task
            assert worker_service._heartbeat_task is task

    # Both worker and heartbeat tasks get cancelled
    assert task.cancel.call_count == 2


@pytest.mark.asyncio
async def test_health_reports_worker_task_state():
    from unittest.mock import AsyncMock, patch

    from app.worker import __main__ as worker_service

    task = MagicMock()
    task.done.return_value = False
    worker_service._worker_task = task

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock()

    with patch("app.core.database.async_session_maker", return_value=mock_session):
        result = await worker_service.health()

    assert result == {
        "status": "healthy",
        "service": "worker",
        "task_alive": True,
        "database": "connected",
    }


@pytest.mark.asyncio
async def test_work_loop_calls_startup_worker_loop_and_shutdown_in_finally():
    from app.worker import __main__ as worker_service

    order: list[str] = []
    startup = AsyncMock(side_effect=lambda: order.append("startup"))
    shutdown = AsyncMock(side_effect=lambda: order.append("shutdown"))

    call_count = 0

    async def fake_worker_loop(functions, queue_name):
        nonlocal call_count
        call_count += 1
        order.append(f"worker:{queue_name}:{sorted(functions)}")
        if call_count == 1:
            raise RuntimeError("stop")
        # Second call: simulate normal exit
        raise asyncio.CancelledError

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
        # Patch asyncio.sleep to avoid real delay
        mp.setattr(asyncio, "sleep", AsyncMock())
        with pytest.raises(asyncio.CancelledError):
            await worker_service.work_loop()

    assert order[0] == "startup"
    assert order[1] == "worker:priority:['alpha']"
    # After crash, it restarts and calls worker_loop again
    assert order[2] == "worker:priority:['alpha']"
    assert order[-1] == "shutdown"
    startup.assert_awaited_once()
    shutdown.assert_awaited_once()
