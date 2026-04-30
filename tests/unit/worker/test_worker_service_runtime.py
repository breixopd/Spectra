"""Unit tests for the worker service runtime wrapper."""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

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
    from spectra_worker import __main__ as worker_service

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

    from spectra_worker import __main__ as worker_service

    task = MagicMock()
    task.done.return_value = False
    worker_service._worker_task = task

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock()

    from fastapi import Response

    mock_response = Response()
    with patch("app.core.database.async_session_maker", return_value=mock_session):
        result = await worker_service.health(mock_response)

    assert result == {
        "status": "healthy",
        "service": "worker",
        "task_alive": True,
        "database": "connected",
    }


@pytest.mark.asyncio
async def test_work_loop_calls_startup_worker_loop_and_shutdown_in_finally():
    from spectra_worker import __main__ as worker_service

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
        return

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.infrastructure.queue",
            make_module("app.infrastructure.queue", worker_loop=fake_worker_loop),
        )
        import spectra_worker as _sw

        mp.setattr(_sw, "_WORKER_FUNCTIONS", ["alpha"])
        mp.setattr("spectra_worker.lifecycle.startup", startup)
        mp.setattr("spectra_worker.lifecycle.shutdown", shutdown)
        mp.setenv("QUEUE_NAME", "priority")
        # Patch asyncio.sleep to avoid real delay
        mp.setattr(asyncio, "sleep", AsyncMock())
        await worker_service.work_loop()

    assert order[0] == "startup"
    assert order[1] == "worker:priority:['alpha']"
    # After crash, it restarts and calls worker_loop again
    assert order[2] == "worker:priority:['alpha']"
    assert order[-1] == "shutdown"
    startup.assert_awaited_once()
    shutdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_health_reports_db_failure():
    from unittest.mock import patch

    from spectra_worker import __main__ as worker_service

    task = MagicMock()
    task.done.return_value = False
    worker_service._worker_task = task

    from fastapi import Response

    mock_response = Response()
    with patch("app.core.database.async_session_maker", side_effect=RuntimeError("db down")):
        result = await worker_service.health(mock_response)

    assert result["status"] == "degraded"
    assert result["database"] == "disconnected"


@pytest.mark.asyncio
async def test_internal_shell_listener_start():
    from spectra_worker import __main__ as worker_service

    with patch("spectra_worker.__main__.shell_manager") as mock_shell:
        mock_shell.start_listener.return_value = 4444
        result = await worker_service.internal_start_shell_listener(
            MagicMock(session_id="s1", target="1.2.3.4", mission_id="m1", port=0, ttl_seconds=900)
        )
        assert result["port"] == 4444


@pytest.mark.asyncio
async def test_internal_shell_listener_start_failure():
    from fastapi import HTTPException

    from spectra_worker import __main__ as worker_service

    with patch("spectra_worker.__main__.shell_manager") as mock_shell:
        mock_shell.start_listener.side_effect = RuntimeError("no ports")
        with pytest.raises(HTTPException):
            await worker_service.internal_start_shell_listener(
                MagicMock(session_id="s1", target="1.2.3.4", mission_id="m1", port=0, ttl_seconds=900)
            )


@pytest.mark.asyncio
async def test_internal_shell_listener_list():
    from spectra_worker import __main__ as worker_service

    with patch("spectra_worker.__main__.shell_manager") as mock_shell:
        mock_shell.list_listeners.return_value = [{"session_id": "s1"}]
        result = await worker_service.internal_list_shell_listeners()
        assert len(result) == 1


@pytest.mark.asyncio
async def test_internal_shell_listener_stop():
    from spectra_worker import __main__ as worker_service

    with patch("spectra_worker.__main__.shell_manager") as mock_shell:
        mock_shell.stop_listener.return_value = True
        await worker_service.internal_stop_shell_listener("s1")
        mock_shell.stop_listener.assert_called_once_with(session_id="s1")


@pytest.mark.asyncio
async def test_internal_shell_listener_stop_not_found():
    from fastapi import HTTPException

    from spectra_worker import __main__ as worker_service

    with patch("spectra_worker.__main__.shell_manager") as mock_shell:
        mock_shell.stop_listener.return_value = False
        with pytest.raises(HTTPException):
            await worker_service.internal_stop_shell_listener("s1")


@pytest.mark.asyncio
async def test_run_heartbeat():
    from spectra_worker import __main__ as worker_service

    with patch("spectra_worker.lifecycle.heartbeat_loop", new_callable=AsyncMock) as mock_heartbeat:
        with patch.dict("os.environ", {"QUEUE_NAME": "test_queue"}):
            await worker_service._run_heartbeat()

    mock_heartbeat.assert_awaited_once_with("test_queue")
