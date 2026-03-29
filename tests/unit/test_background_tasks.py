"""Unit tests for background maintenance loops."""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers import make_module, reload_module


@pytest.mark.asyncio
async def test_cache_cleanup_loop_purges_expired_entries_once():
    from app.core import background_tasks as background_tasks_module

    background_tasks = reload_module(background_tasks_module)

    cache = SimpleNamespace(purge_expired=AsyncMock(return_value=3))

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(sys.modules, "app.core.cache", make_module("app.core.cache", get_cache=lambda: cache))
        mp.setattr(
            background_tasks.asyncio,
            "sleep",
            AsyncMock(side_effect=[None, asyncio.CancelledError()]),
        )
        await background_tasks.cache_cleanup_loop()

    cache.purge_expired.assert_awaited_once()


@pytest.mark.asyncio
async def test_periodic_cleanup_loop_runs_single_cleanup_cycle():
    from app.core import background_tasks as background_tasks_module

    background_tasks = reload_module(background_tasks_module)

    cleanup = AsyncMock()

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.worker.cleanup_jobs",
            make_module("app.worker.cleanup_jobs", run_all_cleanup=cleanup),
        )
        mp.setattr(
            background_tasks.asyncio,
            "sleep",
            AsyncMock(side_effect=[None, asyncio.CancelledError()]),
        )
        await background_tasks.periodic_cleanup_loop()

    cleanup.assert_awaited_once()


@pytest.mark.asyncio
async def test_cache_cleanup_loop_handles_runtime_errors():
    from app.core import background_tasks as background_tasks_module

    background_tasks = reload_module(background_tasks_module)
    cache = SimpleNamespace(purge_expired=AsyncMock(side_effect=OSError("cache down")))

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(sys.modules, "app.core.cache", make_module("app.core.cache", get_cache=lambda: cache))
        mp.setattr(
            background_tasks.asyncio,
            "sleep",
            AsyncMock(side_effect=[None, asyncio.CancelledError()]),
        )
        await background_tasks.cache_cleanup_loop()

    cache.purge_expired.assert_awaited_once()


@pytest.mark.asyncio
async def test_periodic_cleanup_loop_handles_runtime_errors():
    from app.core import background_tasks as background_tasks_module

    background_tasks = reload_module(background_tasks_module)
    cleanup = AsyncMock(side_effect=RuntimeError("cleanup failed"))

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.worker.cleanup_jobs",
            make_module("app.worker.cleanup_jobs", run_all_cleanup=cleanup),
        )
        mp.setattr(
            background_tasks.asyncio,
            "sleep",
            AsyncMock(side_effect=[None, asyncio.CancelledError()]),
        )
        await background_tasks.periodic_cleanup_loop()

    cleanup.assert_awaited_once()


@pytest.mark.asyncio
async def test_sandbox_watchdog_skips_when_pool_unavailable():
    from app.core import background_tasks

    sandbox_model = type("Sandbox", (), {"status": "running"})

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.models.infrastructure",
            make_module("app.models.infrastructure", Sandbox=sandbox_model),
        )
        mp.setitem(
            sys.modules,
            "app.services.tools.sandbox",
            make_module("app.services.tools.sandbox", get_sandbox_pool=lambda: None),
        )
        mp.setattr(
            background_tasks.asyncio,
            "sleep",
            AsyncMock(side_effect=[None, asyncio.CancelledError()]),
        )
        await background_tasks.sandbox_watchdog_loop()


@pytest.mark.asyncio
async def test_sandbox_watchdog_reaps_stale_sandbox():
    from app.core import background_tasks

    now = datetime.now(UTC)
    sandbox = SimpleNamespace(
        mission_id="mission-12345678",
        container_name="sandbox-1",
        created_at=now - timedelta(minutes=20),
        last_heartbeat=now - timedelta(minutes=10),
    )
    pool = SimpleNamespace(available=True, destroy=AsyncMock())
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [sandbox]
    session.execute = AsyncMock(return_value=result)
    session_ctx = AsyncMock()
    session_ctx.__aenter__ = AsyncMock(return_value=session)
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    sandbox_model = type("Sandbox", (), {"status": "running"})

    class _FakeSelect:
        def where(self, *args, **kwargs):
            return self

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.models.infrastructure",
            make_module("app.models.infrastructure", Sandbox=sandbox_model),
        )
        mp.setitem(
            sys.modules,
            "app.services.tools.sandbox",
            make_module("app.services.tools.sandbox", get_sandbox_pool=lambda: pool),
        )
        mp.setattr(background_tasks, "async_session_maker", MagicMock(return_value=session_ctx))
        mp.setattr(background_tasks, "select", lambda *args, **kwargs: _FakeSelect())
        mp.setattr(
            background_tasks,
            "settings",
            SimpleNamespace(SANDBOX_IDLE_TIMEOUT=60, SANDBOX_HEARTBEAT_INTERVAL=30),
        )
        mp.setattr(
            background_tasks.asyncio,
            "sleep",
            AsyncMock(side_effect=[None, asyncio.CancelledError()]),
        )
        await background_tasks.sandbox_watchdog_loop()

    pool.destroy.assert_awaited_once_with("mission-12345678")


@pytest.mark.asyncio
async def test_sandbox_watchdog_uses_age_when_heartbeat_missing():
    from app.core import background_tasks

    now = datetime.now(UTC)
    sandbox = SimpleNamespace(
        mission_id="mission-87654321",
        container_name="sandbox-2",
        created_at=now - timedelta(minutes=30),
        last_heartbeat=None,
    )
    pool = SimpleNamespace(available=True, destroy=AsyncMock())
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [sandbox]
    session.execute = AsyncMock(return_value=result)
    session_ctx = AsyncMock()
    session_ctx.__aenter__ = AsyncMock(return_value=session)
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    sandbox_model = type("Sandbox", (), {"status": "running"})

    class _FakeSelect:
        def where(self, *args, **kwargs):
            return self

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.models.infrastructure",
            make_module("app.models.infrastructure", Sandbox=sandbox_model),
        )
        mp.setitem(
            sys.modules,
            "app.services.tools.sandbox",
            make_module("app.services.tools.sandbox", get_sandbox_pool=lambda: pool),
        )
        mp.setattr(background_tasks, "async_session_maker", MagicMock(return_value=session_ctx))
        mp.setattr(background_tasks, "select", lambda *args, **kwargs: _FakeSelect())
        mp.setattr(
            background_tasks,
            "settings",
            SimpleNamespace(SANDBOX_IDLE_TIMEOUT=60, SANDBOX_HEARTBEAT_INTERVAL=30),
        )
        mp.setattr(
            background_tasks.asyncio,
            "sleep",
            AsyncMock(side_effect=[None, asyncio.CancelledError()]),
        )
        await background_tasks.sandbox_watchdog_loop()

    pool.destroy.assert_awaited_once_with("mission-87654321")


@pytest.mark.asyncio
async def test_sandbox_watchdog_handles_database_errors():
    from app.core import background_tasks

    pool = SimpleNamespace(available=True)
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=background_tasks.SQLAlchemyError("db down"))
    session_ctx = AsyncMock()
    session_ctx.__aenter__ = AsyncMock(return_value=session)
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    sandbox_model = type("Sandbox", (), {"status": "running"})

    class _FakeSelect:
        def where(self, *args, **kwargs):
            return self

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.models.infrastructure",
            make_module("app.models.infrastructure", Sandbox=sandbox_model),
        )
        mp.setitem(
            sys.modules,
            "app.services.tools.sandbox",
            make_module("app.services.tools.sandbox", get_sandbox_pool=lambda: pool),
        )
        mp.setattr(background_tasks, "async_session_maker", MagicMock(return_value=session_ctx))
        mp.setattr(background_tasks, "select", lambda *args, **kwargs: _FakeSelect())
        mp.setattr(
            background_tasks.asyncio,
            "sleep",
            AsyncMock(side_effect=[None, asyncio.CancelledError()]),
        )
        await background_tasks.sandbox_watchdog_loop()

    session.execute.assert_awaited_once()
