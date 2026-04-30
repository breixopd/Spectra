"""Tests for deterministic advisory lock IDs and lifecycle helpers."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.auth.advisory_locks import advisory_lock_owner, stable_lock_id


def _connection_factory(connection):
    class _ConnectionContext:
        async def __aenter__(self):
            return connection

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def factory():
        return _ConnectionContext()

    return factory


def test_stable_lock_id_is_deterministic_and_bigint_safe():
    value = stable_lock_id("spectra_backup")

    assert value == 5364792680498971710
    assert value == stable_lock_id("spectra_backup")
    assert value != stable_lock_id("spectra_quota_reset")
    assert 0 <= value <= (1 << 63) - 1


def test_scheduler_lock_constants_use_stable_helper():
    import spectra_scheduler.locks as sched_locks

    assert stable_lock_id("spectra_backup") == sched_locks._BACKUP_LOCK_ID
    assert stable_lock_id("spectra_scheduler_leader") == sched_locks._SCHEDULER_LEADER_LOCK_ID


@pytest.mark.asyncio
async def test_advisory_lock_owner_yields_none_when_lock_is_unavailable():
    acquire_result = MagicMock()
    acquire_result.scalar.return_value = False
    connection = MagicMock()
    connection.execute = AsyncMock(return_value=acquire_result)

    async with advisory_lock_owner(123, connection_factory=_connection_factory(connection)) as lock_owner:
        assert lock_owner is None

    assert connection.execute.await_count == 1
    assert "pg_try_advisory_lock" in str(connection.execute.await_args_list[0].args[0])


@pytest.mark.asyncio
async def test_advisory_lock_owner_releases_lock_on_exit():
    acquire_result = MagicMock()
    acquire_result.scalar.return_value = True
    unlock_result = MagicMock()
    unlock_result.scalar.return_value = True
    connection = MagicMock()
    connection.execute = AsyncMock(side_effect=[acquire_result, unlock_result])

    async with advisory_lock_owner(456, connection_factory=_connection_factory(connection)) as lock_owner:
        assert lock_owner is connection

    assert connection.execute.await_count == 2
    assert "pg_advisory_unlock" in str(connection.execute.await_args_list[1].args[0])
    assert connection.execute.await_args_list[1].args[1] == {"lock_id": 456}


@pytest.mark.asyncio
async def test_advisory_lock_owner_releases_lock_on_cancellation():
    acquire_result = MagicMock()
    acquire_result.scalar.return_value = True
    unlock_result = MagicMock()
    unlock_result.scalar.return_value = True
    connection = MagicMock()
    connection.execute = AsyncMock(side_effect=[acquire_result, unlock_result])

    with pytest.raises(asyncio.CancelledError):
        async with advisory_lock_owner(789, connection_factory=_connection_factory(connection)):
            raise asyncio.CancelledError()

    assert connection.execute.await_count == 2
    assert "pg_advisory_unlock" in str(connection.execute.await_args_list[1].args[0])
