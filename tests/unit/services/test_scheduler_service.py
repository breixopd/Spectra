"""Unit tests for the scheduler service."""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Response

import spectra_scheduler.async_ops as scheduler_async_ops
import spectra_scheduler.locking as scheduler_locking
import spectra_scheduler.loops.core_loops as scheduler_core_loops
import spectra_scheduler.routes as scheduler_routes
import spectra_scheduler.service as scheduler_svc_mod
import spectra_scheduler.state as scheduler_state
from tests.helpers import make_module


class _AwaitableTask:
    def __init__(self, exc: BaseException | None = None):
        self._exc = exc
        self.cancel = MagicMock()

    def __await__(self):
        async def _inner():
            if self._exc is not None:
                raise self._exc
            return None

        return _inner().__await__()


class _HealthTask:
    def __init__(self, *, done: bool):
        self._done = done

    def done(self) -> bool:
        return self._done


@pytest.mark.asyncio
async def test_start_schedules_expected_background_tasks():
    import spectra_scheduler.main as scheduler_service

    service = scheduler_service.SchedulerService()
    tasks: list[MagicMock] = []
    scheduled_loops: list[str] = []

    def fake_create_safe_task(coro, *, name=None, logger_=None):
        scheduled_loops.append(coro.cr_code.co_name)
        coro.close()
        task = MagicMock()
        tasks.append(task)
        return task

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(scheduler_svc_mod, "create_safe_task", fake_create_safe_task)
        mp.setattr(scheduler_async_ops, "gather", AsyncMock(return_value=None))
        await service.start()

    assert service.running is True
    assert set(scheduled_loops) >= {
        "_sandbox_watchdog",
        "_quota_reset",
        "_metrics_collector",
        "_health_reporter",
        "_infrastructure_monitor",
        "_backup_scheduler",
    }
    assert service.tasks == tasks


@pytest.mark.asyncio
async def test_postgres_pool_pressure_alerts_when_threshold_exceeded():
    import app.core.database as database
    import spectra_scheduler.main as scheduler_service

    class FakePool:
        _max_overflow = 0

        def checkedout(self):
            return 9

        def size(self):
            return 10

    fake_engine = SimpleNamespace(sync_engine=SimpleNamespace(pool=FakePool()))
    settings = SimpleNamespace(INFRA_MONITOR_PG_THRESHOLD=80)
    service = scheduler_service.SchedulerService()
    service._send_infra_alert = AsyncMock()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(database, "engine", fake_engine)
        await service._check_postgres_pool_pressure(settings)

    service._send_infra_alert.assert_awaited_once()


@pytest.mark.asyncio
async def test_redis_memory_pressure_alerts_when_threshold_exceeded():
    import redis.asyncio as aioredis

    import spectra_scheduler.main as scheduler_service

    client = SimpleNamespace(
        info=AsyncMock(return_value={"used_memory": 90, "maxmemory": 100}),
        aclose=AsyncMock(),
    )
    settings = SimpleNamespace(
        REDIS_URL="redis://redis:6379/0",
        RATE_LIMIT_STORAGE="",
        INFRA_MONITOR_REDIS_THRESHOLD=85,
    )
    service = scheduler_service.SchedulerService()
    service._send_infra_alert = AsyncMock()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(aioredis, "from_url", MagicMock(return_value=client))
        await service._check_redis_memory_pressure(settings)

    service._send_infra_alert.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_cancels_all_running_tasks():
    import spectra_scheduler.main as scheduler_service

    service = scheduler_service.SchedulerService()
    service.running = True
    service.tasks = [MagicMock(), MagicMock()]

    await service.stop()

    assert service.running is False
    service.tasks[0].cancel.assert_called_once()
    service.tasks[1].cancel.assert_called_once()


@pytest.mark.asyncio
async def test_sandbox_watchdog_loop_runs_single_iteration():
    import spectra_scheduler.main as scheduler_service

    service = scheduler_service.SchedulerService()
    service.running = True
    watchdog = AsyncMock(side_effect=lambda: setattr(service, "running", False))

    @asynccontextmanager
    async def fake_lock_owner(lock_id, *, connection_factory):
        yield object()

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.infrastructure.background_tasks",
            make_module("app.infrastructure.background_tasks", sandbox_watchdog_loop=watchdog),
        )
        mp.setattr(scheduler_locking, "advisory_lock_owner", fake_lock_owner)
        mp.setattr(scheduler_async_ops, "sleep", AsyncMock())
        await service._sandbox_watchdog()

    watchdog.assert_awaited_once()


@pytest.mark.asyncio
async def test_sandbox_watchdog_loop_handles_errors_and_continues():
    import spectra_scheduler.main as scheduler_service

    service = scheduler_service.SchedulerService()
    service.running = True
    watchdog = AsyncMock(side_effect=ValueError("watchdog failed"))

    @asynccontextmanager
    async def fake_lock_owner(lock_id, *, connection_factory):
        yield object()

    async def stop_after_sleep(seconds):
        service.running = False

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.infrastructure.background_tasks",
            make_module("app.infrastructure.background_tasks", sandbox_watchdog_loop=watchdog),
        )
        mp.setattr(scheduler_locking, "advisory_lock_owner", fake_lock_owner)
        mp.setattr(scheduler_async_ops, "sleep", AsyncMock(side_effect=stop_after_sleep))
        await service._sandbox_watchdog()

    watchdog.assert_awaited_once()


@pytest.mark.asyncio
async def test_sandbox_watchdog_skips_work_when_lock_not_acquired():
    import spectra_scheduler.main as scheduler_service

    service = scheduler_service.SchedulerService()
    service.running = True
    watchdog = AsyncMock()

    @asynccontextmanager
    async def fake_lock_owner(lock_id, *, connection_factory):
        yield None

    async def stop_after_sleep(seconds):
        service.running = False

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.infrastructure.background_tasks",
            make_module("app.infrastructure.background_tasks", sandbox_watchdog_loop=watchdog),
        )
        mp.setattr(scheduler_locking, "advisory_lock_owner", fake_lock_owner)
        mp.setattr(scheduler_async_ops, "sleep", AsyncMock(side_effect=stop_after_sleep))
        await service._sandbox_watchdog()

    watchdog.assert_not_awaited()


@pytest.mark.asyncio
async def test_quota_reset_runs_single_iteration():
    import spectra_scheduler.main as scheduler_service

    service = scheduler_service.SchedulerService()
    service.running = True
    tracker = SimpleNamespace(reset_daily_counters=AsyncMock(side_effect=lambda: setattr(service, "running", False)))

    class _FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 3, 29, 23, 15, tzinfo=UTC)

    @asynccontextmanager
    async def fake_lock_owner(lock_id, *, connection_factory):
        yield object()

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.services.billing.usage_tracker",
            make_module("app.services.billing.usage_tracker", UsageTracker=lambda: tracker),
        )
        mp.setattr(scheduler_core_loops, "datetime", _FakeDateTime)
        mp.setattr(scheduler_locking, "advisory_lock_owner", fake_lock_owner)
        mp.setattr(scheduler_async_ops, "sleep", AsyncMock())
        await service._quota_reset()

    tracker.reset_daily_counters.assert_awaited_once()


@pytest.mark.asyncio
async def test_quota_reset_handles_reset_errors():
    import spectra_scheduler.main as scheduler_service

    service = scheduler_service.SchedulerService()
    service.running = True

    async def reset_daily_counters():
        service.running = False
        raise RuntimeError("quota failed")

    tracker = SimpleNamespace(reset_daily_counters=AsyncMock(side_effect=reset_daily_counters))

    class _FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 3, 29, 23, 15, tzinfo=UTC)

    @asynccontextmanager
    async def fake_lock_owner(lock_id, *, connection_factory):
        yield object()

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.services.billing.usage_tracker",
            make_module("app.services.billing.usage_tracker", UsageTracker=lambda: tracker),
        )
        mp.setattr(scheduler_core_loops, "datetime", _FakeDateTime)
        mp.setattr(scheduler_locking, "advisory_lock_owner", fake_lock_owner)
        mp.setattr(scheduler_async_ops, "sleep", AsyncMock())
        await service._quota_reset()

    tracker.reset_daily_counters.assert_awaited_once()


@pytest.mark.asyncio
async def test_metrics_collector_runs_single_iteration():
    import spectra_scheduler.main as scheduler_service

    service = scheduler_service.SchedulerService()
    service.running = True
    store = SimpleNamespace(collect=AsyncMock(side_effect=lambda: setattr(service, "running", False)))

    @asynccontextmanager
    async def fake_lock_owner(lock_id, *, connection_factory):
        yield object()

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.infrastructure.metrics_store",
            make_module("app.infrastructure.metrics_store", get_metrics_store=lambda: store),
        )
        mp.setattr(scheduler_locking, "advisory_lock_owner", fake_lock_owner)
        mp.setattr(scheduler_async_ops, "sleep", AsyncMock())
        await service._metrics_collector()

    store.collect.assert_awaited_once()


@pytest.mark.asyncio
async def test_metrics_collector_handles_collection_errors():
    import spectra_scheduler.main as scheduler_service

    service = scheduler_service.SchedulerService()
    service.running = True

    async def collect():
        service.running = False
        raise RuntimeError("collect failed")

    store = SimpleNamespace(collect=AsyncMock(side_effect=collect))

    @asynccontextmanager
    async def fake_lock_owner(lock_id, *, connection_factory):
        yield object()

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.infrastructure.metrics_store",
            make_module("app.infrastructure.metrics_store", get_metrics_store=lambda: store),
        )
        mp.setattr(scheduler_locking, "advisory_lock_owner", fake_lock_owner)
        mp.setattr(scheduler_async_ops, "sleep", AsyncMock())
        await service._metrics_collector()

    store.collect.assert_awaited_once()


@pytest.mark.asyncio
async def test_health_reporter_runs_single_iteration():
    import spectra_scheduler.main as scheduler_service

    service = scheduler_service.SchedulerService()
    service.running = True
    cache = SimpleNamespace(set=AsyncMock(side_effect=lambda *args, **kwargs: setattr(service, "running", False)))

    @asynccontextmanager
    async def fake_lock_owner(lock_id, *, connection_factory):
        yield object()

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.infrastructure.cache",
            make_module("app.infrastructure.cache", get_cache=lambda: cache),
        )
        mp.setattr(scheduler_locking, "advisory_lock_owner", fake_lock_owner)
        mp.setattr(scheduler_async_ops, "sleep", AsyncMock())
        await service._health_reporter()

    cache.set.assert_awaited_once()


@pytest.mark.asyncio
async def test_health_reporter_swallows_cache_errors():
    import spectra_scheduler.main as scheduler_service

    service = scheduler_service.SchedulerService()
    service.running = True
    cache = SimpleNamespace(set=AsyncMock(side_effect=OSError("cache down")))

    @asynccontextmanager
    async def fake_lock_owner(lock_id, *, connection_factory):
        yield object()

    async def stop_after_sleep(seconds):
        service.running = False

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.infrastructure.cache",
            make_module("app.infrastructure.cache", get_cache=lambda: cache),
        )
        mp.setattr(scheduler_locking, "advisory_lock_owner", fake_lock_owner)
        mp.setattr(scheduler_async_ops, "sleep", AsyncMock(side_effect=stop_after_sleep))
        await service._health_reporter()

    cache.set.assert_awaited_once()


@pytest.mark.asyncio
async def test_backup_scheduler_runs_single_iteration():
    import spectra_scheduler.main as scheduler_service

    service = scheduler_service.SchedulerService()
    service.running = True
    settings = SimpleNamespace(BACKUP_ENABLED=True, BACKUP_SCHEDULE_HOURS=0)
    backup_service = SimpleNamespace(
        create_backup=AsyncMock(side_effect=lambda: setattr(service, "running", False) or {"status": "ok"})
    )

    @asynccontextmanager
    async def fake_lock_owner(lock_id, *, connection_factory):
        yield object()

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.core.config",
            make_module("app.core.config", get_settings=lambda: settings),
        )
        mp.setitem(
            sys.modules,
            "app.services.infrastructure.backup",
            make_module("app.services.infrastructure.backup", BackupService=lambda: backup_service),
        )
        mp.setattr(scheduler_locking, "advisory_lock_owner", fake_lock_owner)
        mp.setattr(scheduler_async_ops, "sleep", AsyncMock())
        await service._backup_scheduler()

    backup_service.create_backup.assert_awaited_once()


@pytest.mark.asyncio
async def test_backup_scheduler_skips_work_when_backups_disabled():
    import spectra_scheduler.main as scheduler_service

    service = scheduler_service.SchedulerService()
    service.running = True
    settings = SimpleNamespace(BACKUP_ENABLED=False, BACKUP_SCHEDULE_HOURS=1)
    sleep_calls: list[int] = []

    async def record_sleep(seconds):
        sleep_calls.append(seconds)
        service.running = False

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.core.config",
            make_module("app.core.config", get_settings=lambda: settings),
        )
        mp.setattr(scheduler_async_ops, "sleep", AsyncMock(side_effect=record_sleep))
        await service._backup_scheduler()

    assert 3600 in sleep_calls


@pytest.mark.asyncio
async def test_backup_scheduler_handles_backup_errors():
    import spectra_scheduler.main as scheduler_service

    service = scheduler_service.SchedulerService()
    service.running = True
    settings = SimpleNamespace(BACKUP_ENABLED=True, BACKUP_SCHEDULE_HOURS=0)

    async def create_backup():
        service.running = False
        raise RuntimeError("backup failed")

    backup_service = SimpleNamespace(create_backup=AsyncMock(side_effect=create_backup))

    @asynccontextmanager
    async def fake_lock_owner(lock_id, *, connection_factory):
        yield object()

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.core.config",
            make_module("app.core.config", get_settings=lambda: settings),
        )
        mp.setitem(
            sys.modules,
            "app.services.infrastructure.backup",
            make_module("app.services.infrastructure.backup", BackupService=lambda: backup_service),
        )
        mp.setattr(scheduler_locking, "advisory_lock_owner", fake_lock_owner)
        mp.setattr(scheduler_async_ops, "sleep", AsyncMock())
        await service._backup_scheduler()

    backup_service.create_backup.assert_awaited_once()


@pytest.mark.asyncio
async def test_image_update_check_skips_registry_when_auto_update_disabled():
    import spectra_scheduler.main as scheduler_service

    service = scheduler_service.SchedulerService()
    service.running = True
    settings = SimpleNamespace(IMAGE_AUTO_UPDATE=False, IMAGE_CHECK_INTERVAL=0)
    image_updater = SimpleNamespace(check_and_update_services=AsyncMock())

    async def stop_after_sleep(seconds):
        service.running = False

    @asynccontextmanager
    async def fake_lock_owner(lock_id, *, connection_factory):
        yield object()

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.core.config",
            make_module("app.core.config", get_settings=lambda: settings),
        )
        mp.setitem(
            sys.modules,
            "app.services.scaling.image_updater",
            make_module("app.services.scaling.image_updater", check_and_update_services=image_updater.check_and_update_services),
        )
        mp.setattr(scheduler_locking, "advisory_lock_owner", fake_lock_owner)
        mp.setattr(scheduler_async_ops, "sleep", AsyncMock(side_effect=stop_after_sleep))
        await service._image_update_check()

    image_updater.check_and_update_services.assert_not_awaited()


@pytest.mark.asyncio
async def test_image_update_check_runs_when_auto_update_enabled():
    import spectra_scheduler.main as scheduler_service

    service = scheduler_service.SchedulerService()
    service.running = True
    settings = SimpleNamespace(IMAGE_AUTO_UPDATE=True, IMAGE_CHECK_INTERVAL=0)
    image_updater = SimpleNamespace(
        check_and_update_services=AsyncMock(side_effect=lambda **kwargs: setattr(service, "running", False) or []),
    )

    @asynccontextmanager
    async def fake_lock_owner(lock_id, *, connection_factory):
        yield object()

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.core.config",
            make_module("app.core.config", get_settings=lambda: settings),
        )
        mp.setitem(
            sys.modules,
            "app.services.scaling.image_updater",
            make_module("app.services.scaling.image_updater", check_and_update_services=image_updater.check_and_update_services),
        )
        mp.setattr(scheduler_locking, "advisory_lock_owner", fake_lock_owner)
        mp.setattr(scheduler_async_ops, "sleep", AsyncMock())
        await service._image_update_check()

    image_updater.check_and_update_services.assert_awaited_once_with(apply=True)


@pytest.mark.asyncio
async def test_health_reports_scheduler_running_state():
    import spectra_scheduler.main as scheduler_service

    scheduler_state._scheduler_instance = SimpleNamespace(
        running=True, health=lambda: {"status": "healthy", "tasks": {}, "running": True}
    )
    response = Response()
    assert await scheduler_service.health(response) == {
        "status": "healthy",
        "tasks": {},
        "running": True,
        "service": "scheduler",
    }
    assert response.status_code == 200

    scheduler_state._scheduler_instance = None
    response = Response()
    assert await scheduler_service.health(response) == {"status": "starting", "service": "scheduler"}
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_route_returns_503_when_scheduler_is_degraded():
    import spectra_scheduler.main as scheduler_service

    scheduler_state._scheduler_instance = SimpleNamespace(
        running=True,
        health=lambda: {"status": "degraded", "tasks": {"quota_reset": "dead"}, "running": True},
    )

    response = Response()

    result = await scheduler_service.health(response)

    assert response.status_code == 503
    assert result == {
        "status": "degraded",
        "tasks": {"quota_reset": "dead"},
        "running": True,
        "service": "scheduler",
    }


@pytest.mark.asyncio
async def test_health_route_keeps_standby_at_http_200():
    import spectra_scheduler.main as scheduler_service

    scheduler_state._scheduler_instance = SimpleNamespace(
        running=False,
        health=lambda: {"status": "standby", "tasks": {}, "running": False},
    )

    response = Response()

    result = await scheduler_service.health(response)

    assert response.status_code == 200
    assert result == {
        "status": "standby",
        "tasks": {},
        "running": False,
        "service": "scheduler",
    }


def test_service_health_reports_task_states_when_healthy():
    import spectra_scheduler.main as scheduler_service

    service = scheduler_service.SchedulerService()
    service.running = True
    service._named_tasks = {
        task_name: _HealthTask(done=False)
        for task_name, _method_name in scheduler_service._SCHEDULER_TASK_SPECS
    }

    result = service.health()

    assert result["status"] == "healthy"
    assert result["running"] is True
    assert set(result["tasks"].values()) == {"alive"}


def test_service_health_degrades_when_any_task_is_dead_or_missing():
    import spectra_scheduler.main as scheduler_service

    service = scheduler_service.SchedulerService()
    service.running = True
    service._named_tasks = {
        task_name: _HealthTask(done=False)
        for task_name, _method_name in scheduler_service._SCHEDULER_TASK_SPECS
    }
    service._named_tasks["quota_reset"] = _HealthTask(done=True)
    service._named_tasks.pop("disk_monitor")

    result = service.health()

    assert result["status"] == "degraded"
    assert result["tasks"]["quota_reset"] == "dead"
    assert result["tasks"]["disk_monitor"] == "missing"


def test_service_health_is_standby_when_not_running():
    import spectra_scheduler.main as scheduler_service

    service = scheduler_service.SchedulerService()

    result = service.health()

    assert result["status"] == "standby"
    assert result["running"] is False
    assert set(result["tasks"].values()) == {"missing"}


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_scheduler_service():
    import spectra_scheduler.main as scheduler_service

    service = SimpleNamespace(start=AsyncMock(), stop=AsyncMock(), running=True)
    task = _AwaitableTask(exc=asyncio.CancelledError())

    def fake_create_safe_task(coro, *, name=None, logger_=None):
        coro.close()
        return task

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(scheduler_routes, "SchedulerService", lambda: service)
        mp.setattr(scheduler_routes, "create_safe_task", fake_create_safe_task)
        async with scheduler_service.lifespan(scheduler_service.app):
            assert scheduler_state._scheduler_instance is service

    service.stop.assert_awaited_once()
    task.cancel.assert_called_once()


@pytest.mark.asyncio
async def test_main_registers_signal_handlers_and_starts_scheduler():
    import spectra_scheduler.main as scheduler_service

    service = SimpleNamespace(start=AsyncMock(), stop=AsyncMock())
    loop = SimpleNamespace(add_signal_handler=MagicMock())

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(scheduler_service, "SchedulerService", lambda: service)
        mp.setattr(scheduler_service.asyncio, "get_running_loop", lambda: loop)
        await scheduler_service.main()

    assert loop.add_signal_handler.call_count == 2
    service.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_leader_election_runs_scheduler_inside_lock_context():
    import spectra_scheduler.main as scheduler_service

    events: list[str] = []

    async def start():
        events.append("start")

    scheduler = SimpleNamespace(start=AsyncMock(side_effect=start))

    @asynccontextmanager
    async def fake_lock_owner(lock_id, *, connection_factory):
        events.append("enter")
        try:
            yield object()
        finally:
            events.append("exit")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(scheduler_locking, "advisory_lock_owner", fake_lock_owner)
        await scheduler_service._leader_election_loop(scheduler)

    scheduler.start.assert_awaited_once()
    assert events == ["enter", "start", "exit"]
