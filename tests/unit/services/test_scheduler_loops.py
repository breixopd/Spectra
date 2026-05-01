"""Unit tests for scheduler DB and Docker maintenance loops (mocked I/O)."""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import sqlalchemy.ext.asyncio as sa_asyncio

import spectra_scheduler.async_ops as scheduler_async_ops
import spectra_scheduler.locking as scheduler_locking
import spectra_scheduler.service as scheduler_service_mod
from app.services.scaling.image_updater import ImageUpdateResult
from tests.helpers import make_module


@pytest.mark.asyncio
async def test_db_maintenance_runs_vacuum_when_lock_acquired():
    service = scheduler_service_mod.SchedulerService()
    service.running = True
    conn = MagicMock()
    conn.execute = AsyncMock()
    settings_ns = SimpleNamespace(
        DB_MAINTENANCE_INTERVAL=0,
        DATABASE_URL=SimpleNamespace(get_secret_value=lambda: "postgresql+asyncpg://u:p@localhost/db"),
    )

    @asynccontextmanager
    async def fake_connect():
        yield conn

    engine = MagicMock()
    engine.connect = MagicMock(side_effect=fake_connect)
    engine.dispose = AsyncMock()

    @asynccontextmanager
    async def fake_lock_owner(lock_id, *, connection_factory):
        yield object()

    sleep_calls = 0

    async def sleep_then_stop_after_second_iteration(_seconds):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            service.running = False

    create_mock = MagicMock(return_value=engine)

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.core.config",
            make_module("app.core.config", get_settings=lambda: settings_ns),
        )
        mp.setattr(scheduler_locking, "advisory_lock_owner", fake_lock_owner)
        mp.setattr(scheduler_async_ops, "sleep", AsyncMock(side_effect=sleep_then_stop_after_second_iteration))
        mp.setattr(sa_asyncio, "create_async_engine", create_mock)
        await service._db_maintenance()

    create_mock.assert_called_once()
    engine.dispose.assert_awaited_once()
    assert conn.execute.await_count == 5


@pytest.mark.asyncio
async def test_db_maintenance_skips_when_lock_not_acquired():
    service = scheduler_service_mod.SchedulerService()
    service.running = True
    settings_ns = SimpleNamespace(
        DB_MAINTENANCE_INTERVAL=0,
        DATABASE_URL=SimpleNamespace(get_secret_value=lambda: "postgresql+asyncpg://u:p@localhost/db"),
    )

    @asynccontextmanager
    async def fake_lock_owner(lock_id, *, connection_factory):
        yield None

    sleep_calls = 0

    async def sleep_then_stop_after_second_iteration(_seconds):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            service.running = False

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.core.config",
            make_module("app.core.config", get_settings=lambda: settings_ns),
        )
        mp.setattr(scheduler_locking, "advisory_lock_owner", fake_lock_owner)
        mp.setattr(scheduler_async_ops, "sleep", AsyncMock(side_effect=sleep_then_stop_after_second_iteration))
        spy_engine = MagicMock()
        mp.setattr(sa_asyncio, "create_async_engine", spy_engine)
        await service._db_maintenance()

    spy_engine.assert_not_called()


@pytest.mark.asyncio
async def test_db_maintenance_handles_vacuum_errors():
    service = scheduler_service_mod.SchedulerService()
    service.running = True
    conn = MagicMock()
    conn.execute = AsyncMock(side_effect=RuntimeError("vacuum failed"))
    settings_ns = SimpleNamespace(
        DB_MAINTENANCE_INTERVAL=0,
        DATABASE_URL=SimpleNamespace(get_secret_value=lambda: "postgresql+asyncpg://u:p@localhost/db"),
    )

    @asynccontextmanager
    async def fake_connect():
        yield conn

    engine = MagicMock()
    engine.connect = MagicMock(side_effect=fake_connect)
    engine.dispose = AsyncMock()

    @asynccontextmanager
    async def fake_lock_owner(lock_id, *, connection_factory):
        yield object()

    sleep_calls = 0

    async def sleep_then_stop_after_second_iteration(_seconds):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            service.running = False

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.core.config",
            make_module("app.core.config", get_settings=lambda: settings_ns),
        )
        mp.setattr(scheduler_locking, "advisory_lock_owner", fake_lock_owner)
        mp.setattr(scheduler_async_ops, "sleep", AsyncMock(side_effect=sleep_then_stop_after_second_iteration))
        mp.setattr(sa_asyncio, "create_async_engine", MagicMock(return_value=engine))
        await service._db_maintenance()

    conn.execute.assert_awaited()
    engine.dispose.assert_not_awaited()


@pytest.mark.asyncio
async def test_db_maintenance_handles_engine_creation_errors():
    service = scheduler_service_mod.SchedulerService()
    service.running = True
    settings_ns = SimpleNamespace(
        DB_MAINTENANCE_INTERVAL=0,
        DATABASE_URL=SimpleNamespace(get_secret_value=lambda: "postgresql+asyncpg://u:p@localhost/db"),
    )

    @asynccontextmanager
    async def fake_lock_owner(lock_id, *, connection_factory):
        yield object()

    sleep_calls = 0

    async def sleep_then_stop_after_second_iteration(_seconds):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            service.running = False

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.core.config",
            make_module("app.core.config", get_settings=lambda: settings_ns),
        )
        mp.setattr(scheduler_locking, "advisory_lock_owner", fake_lock_owner)
        mp.setattr(scheduler_async_ops, "sleep", AsyncMock(side_effect=sleep_then_stop_after_second_iteration))
        mp.setattr(
            sa_asyncio,
            "create_async_engine",
            MagicMock(side_effect=OSError("no engine")),
        )
        await service._db_maintenance()


@pytest.mark.asyncio
async def test_docker_cleanup_runs_prune_sequence_when_lock_acquired():
    service = scheduler_service_mod.SchedulerService()
    service.running = True
    settings_ns = SimpleNamespace(DOCKER_CLEANUP_INTERVAL=0)
    prune_containers = AsyncMock()
    prune_images = AsyncMock()
    prune_volumes = AsyncMock()

    @asynccontextmanager
    async def fake_lock_owner(lock_id, *, connection_factory):
        yield object()

    sleep_calls = 0

    async def sleep_then_stop_after_second_iteration(_seconds):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            service.running = False

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.core.config",
            make_module("app.core.config", get_settings=lambda: settings_ns),
        )
        mp.setitem(
            sys.modules,
            "app.services.scaling.docker_client",
            make_module(
                "app.services.scaling.docker_client",
                prune_containers=prune_containers,
                prune_images=prune_images,
                prune_volumes=prune_volumes,
            ),
        )
        mp.setattr(scheduler_locking, "advisory_lock_owner", fake_lock_owner)
        mp.setattr(scheduler_async_ops, "sleep", AsyncMock(side_effect=sleep_then_stop_after_second_iteration))
        await service._docker_cleanup()

    prune_containers.assert_any_await(filters={"until": ["48h"]})
    prune_images.assert_awaited_once_with(filters={"until": ["168h"]})
    prune_volumes.assert_awaited_once()
    prune_containers.assert_any_await(
        filters={
            "label": ["com.docker.swarm.task"],
            "status": ["exited"],
        }
    )
    assert prune_containers.await_count == 2


@pytest.mark.asyncio
async def test_docker_cleanup_skips_when_lock_not_acquired():
    service = scheduler_service_mod.SchedulerService()
    service.running = True
    settings_ns = SimpleNamespace(DOCKER_CLEANUP_INTERVAL=0)
    prune_containers = AsyncMock()

    @asynccontextmanager
    async def fake_lock_owner(lock_id, *, connection_factory):
        yield None

    sleep_calls = 0

    async def sleep_then_stop_after_second_iteration(_seconds):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            service.running = False

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.core.config",
            make_module("app.core.config", get_settings=lambda: settings_ns),
        )
        mp.setitem(
            sys.modules,
            "app.services.scaling.docker_client",
            make_module(
                "app.services.scaling.docker_client",
                prune_containers=prune_containers,
                prune_images=AsyncMock(),
                prune_volumes=AsyncMock(),
            ),
        )
        mp.setattr(scheduler_locking, "advisory_lock_owner", fake_lock_owner)
        mp.setattr(scheduler_async_ops, "sleep", AsyncMock(side_effect=sleep_then_stop_after_second_iteration))
        await service._docker_cleanup()

    prune_containers.assert_not_awaited()


@pytest.mark.asyncio
async def test_docker_cleanup_handles_prune_errors():
    service = scheduler_service_mod.SchedulerService()
    service.running = True
    settings_ns = SimpleNamespace(DOCKER_CLEANUP_INTERVAL=0)
    prune_containers = AsyncMock(side_effect=RuntimeError("docker unavailable"))

    @asynccontextmanager
    async def fake_lock_owner(lock_id, *, connection_factory):
        yield object()

    sleep_calls = 0

    async def sleep_then_stop_after_second_iteration(_seconds):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            service.running = False

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "app.core.config",
            make_module("app.core.config", get_settings=lambda: settings_ns),
        )
        mp.setitem(
            sys.modules,
            "app.services.scaling.docker_client",
            make_module(
                "app.services.scaling.docker_client",
                prune_containers=prune_containers,
                prune_images=AsyncMock(),
                prune_volumes=AsyncMock(),
            ),
        )
        mp.setattr(scheduler_locking, "advisory_lock_owner", fake_lock_owner)
        mp.setattr(scheduler_async_ops, "sleep", AsyncMock(side_effect=sleep_then_stop_after_second_iteration))
        await service._docker_cleanup()

    prune_containers.assert_awaited()


@pytest.mark.asyncio
async def test_image_update_check_skips_when_lock_not_acquired(monkeypatch):
    service = scheduler_service_mod.SchedulerService()
    service.running = True
    settings_ns = SimpleNamespace(IMAGE_AUTO_UPDATE=True, IMAGE_CHECK_INTERVAL=0)
    check_and_update = AsyncMock()

    @asynccontextmanager
    async def fake_lock_owner(lock_id, *, connection_factory):
        yield None

    sleep_calls = 0

    async def sleep_then_stop_after_second_iteration(_seconds):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            service.running = False

    monkeypatch.setitem(
        sys.modules,
        "app.core.config",
        make_module("app.core.config", get_settings=lambda: settings_ns),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.services.scaling.image_updater",
        make_module(
            "app.services.scaling.image_updater",
            check_and_update_services=check_and_update,
        ),
    )
    monkeypatch.setattr(scheduler_locking, "advisory_lock_owner", fake_lock_owner)
    monkeypatch.setattr(
        scheduler_async_ops,
        "sleep",
        AsyncMock(side_effect=sleep_then_stop_after_second_iteration),
    )

    await service._image_update_check()

    check_and_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_image_update_check_handles_inner_exceptions(monkeypatch):
    service = scheduler_service_mod.SchedulerService()
    service.running = True
    settings_ns = SimpleNamespace(IMAGE_AUTO_UPDATE=True, IMAGE_CHECK_INTERVAL=0)
    check_and_update = AsyncMock(side_effect=RuntimeError("registry down"))

    @asynccontextmanager
    async def fake_lock_owner(lock_id, *, connection_factory):
        yield object()

    sleep_calls = 0

    async def sleep_then_stop_after_second_iteration(_seconds):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            service.running = False

    monkeypatch.setitem(
        sys.modules,
        "app.core.config",
        make_module("app.core.config", get_settings=lambda: settings_ns),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.services.scaling.image_updater",
        make_module(
            "app.services.scaling.image_updater",
            check_and_update_services=check_and_update,
        ),
    )
    monkeypatch.setattr(scheduler_locking, "advisory_lock_owner", fake_lock_owner)
    monkeypatch.setattr(
        scheduler_async_ops,
        "sleep",
        AsyncMock(side_effect=sleep_then_stop_after_second_iteration),
    )

    await service._image_update_check()

    check_and_update.assert_awaited()


@pytest.mark.asyncio
async def test_image_update_check_skips_when_auto_update_disabled(monkeypatch):
    service = scheduler_service_mod.SchedulerService()
    service.running = True
    settings_ns = SimpleNamespace(IMAGE_AUTO_UPDATE=False, IMAGE_CHECK_INTERVAL=0)
    check_and_update = AsyncMock()

    sleep_calls = 0

    async def sleep_then_stop_after_second_iteration(_seconds):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            service.running = False

    monkeypatch.setitem(
        sys.modules,
        "app.core.config",
        make_module("app.core.config", get_settings=lambda: settings_ns),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.services.scaling.image_updater",
        make_module(
            "app.services.scaling.image_updater",
            check_and_update_services=check_and_update,
        ),
    )
    monkeypatch.setattr(
        scheduler_async_ops,
        "sleep",
        AsyncMock(side_effect=sleep_then_stop_after_second_iteration),
    )

    await service._image_update_check()

    check_and_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_image_update_check_success_notifies(monkeypatch):
    service = scheduler_service_mod.SchedulerService()
    service.running = True
    service._send_update_notification = AsyncMock()
    settings_ns = SimpleNamespace(IMAGE_AUTO_UPDATE=True, IMAGE_CHECK_INTERVAL=0)
    result_ok = ImageUpdateResult(
        service="spectra_app",
        old_digest="sha256:aaa",
        new_digest="sha256:bbb",
        success=True,
        error="",
    )
    check_and_update = AsyncMock(
        side_effect=lambda **kwargs: setattr(service, "running", False) or [result_ok]
    )

    @asynccontextmanager
    async def fake_lock_owner(lock_id, *, connection_factory):
        yield object()

    monkeypatch.setitem(
        sys.modules,
        "app.core.config",
        make_module("app.core.config", get_settings=lambda: settings_ns),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.services.scaling.image_updater",
        make_module(
            "app.services.scaling.image_updater",
            check_and_update_services=check_and_update,
        ),
    )
    monkeypatch.setattr(scheduler_locking, "advisory_lock_owner", fake_lock_owner)
    monkeypatch.setattr(scheduler_async_ops, "sleep", AsyncMock())

    await service._image_update_check()

    check_and_update.assert_awaited_once_with(apply=True)
    service._send_update_notification.assert_awaited_once_with(
        "Auto-updated spectra_app",
        "Digest: sha256:aaa → sha256:bbb",
        level="info",
    )


@pytest.mark.asyncio
async def test_image_update_check_failure_notifies(monkeypatch):
    service = scheduler_service_mod.SchedulerService()
    service.running = True
    service._send_update_notification = AsyncMock()
    settings_ns = SimpleNamespace(IMAGE_AUTO_UPDATE=True, IMAGE_CHECK_INTERVAL=0)
    result_bad = ImageUpdateResult(
        service="spectra_worker",
        old_digest="sha256:old",
        new_digest="sha256:new",
        success=False,
        error="pull denied",
    )
    check_and_update = AsyncMock(
        side_effect=lambda **kwargs: setattr(service, "running", False) or [result_bad]
    )

    @asynccontextmanager
    async def fake_lock_owner(lock_id, *, connection_factory):
        yield object()

    monkeypatch.setitem(
        sys.modules,
        "app.core.config",
        make_module("app.core.config", get_settings=lambda: settings_ns),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.services.scaling.image_updater",
        make_module(
            "app.services.scaling.image_updater",
            check_and_update_services=check_and_update,
        ),
    )
    monkeypatch.setattr(scheduler_locking, "advisory_lock_owner", fake_lock_owner)
    monkeypatch.setattr(scheduler_async_ops, "sleep", AsyncMock())

    await service._image_update_check()

    service._send_update_notification.assert_awaited_once_with(
        "Auto-update failed: spectra_worker",
        "pull denied",
        level="error",
    )


@pytest.mark.asyncio
async def test_send_update_notification_swallows_errors(monkeypatch):
    service = scheduler_service_mod.SchedulerService()

    async def boom(**_kwargs):
        raise OSError("notify down")

    monkeypatch.setitem(
        sys.modules,
        "app.services.notifications",
        make_module("app.services.notifications", send_notification=boom),
    )

    await service._send_update_notification("t", "m", level="info")
