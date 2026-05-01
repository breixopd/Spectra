"""Tests for MissionStateStore."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_cache_entry(key, value, expires_at=None):
    entry = MagicMock()
    entry.key = key
    entry.value = value
    entry.expires_at = expires_at
    return entry


@pytest.mark.asyncio
class TestMissionStateStoreRegister:
    async def test_register_new_mission(self):
        from spectra_platform.services.mission.state_store import MissionStateStore

        session = AsyncMock()
        session.get = AsyncMock(return_value=None)
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch("spectra_platform.services.mission.state_store.async_session_maker", return_value=session):
            store = MissionStateStore()
            await store.register("mission-1", {"status": "created"})

        session.add.assert_called_once()

    async def test_register_updates_existing(self):
        from spectra_platform.services.mission.state_store import MissionStateStore

        existing = _make_cache_entry(
            "mission_state:mission-1",
            {"status": "created"},
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

        session = AsyncMock()
        session.get = AsyncMock(return_value=existing)
        session.commit = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch("spectra_platform.services.mission.state_store.async_session_maker", return_value=session):
            store = MissionStateStore()
            await store.register("mission-1", {"status": "running"})

        assert existing.value == {"status": "running"}


@pytest.mark.asyncio
class TestMissionStateStoreHeartbeat:
    async def test_heartbeat_extends_ttl(self):
        from spectra_platform.services.mission.state_store import MissionStateStore

        old_expiry = datetime.now(UTC) + timedelta(minutes=5)
        entry = _make_cache_entry("mission_state:m-1", {}, expires_at=old_expiry)

        session = AsyncMock()
        session.get = AsyncMock(return_value=entry)
        session.commit = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch("spectra_platform.services.mission.state_store.async_session_maker", return_value=session):
            store = MissionStateStore(ttl_minutes=120)
            await store.heartbeat("m-1")

        # New expiry should be later than old
        assert entry.expires_at > old_expiry

    async def test_heartbeat_noop_if_missing(self):
        from spectra_platform.services.mission.state_store import MissionStateStore

        session = AsyncMock()
        session.get = AsyncMock(return_value=None)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch("spectra_platform.services.mission.state_store.async_session_maker", return_value=session):
            store = MissionStateStore()
            await store.heartbeat("nonexistent")
            # Should not raise


@pytest.mark.asyncio
class TestMissionStateStoreGetState:
    async def test_returns_state(self):
        from spectra_platform.services.mission.state_store import MissionStateStore

        entry = _make_cache_entry(
            "mission_state:m-1",
            {"status": "running", "target": "10.0.0.1"},
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

        session = AsyncMock()
        session.get = AsyncMock(return_value=entry)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch("spectra_platform.services.mission.state_store.async_session_maker", return_value=session):
            store = MissionStateStore()
            state = await store.get_state("m-1")

        assert state == {"status": "running", "target": "10.0.0.1"}

    async def test_returns_none_if_expired(self):
        from spectra_platform.services.mission.state_store import MissionStateStore

        entry = _make_cache_entry(
            "mission_state:m-1",
            {"status": "old"},
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )

        session = AsyncMock()
        session.get = AsyncMock(return_value=entry)
        session.delete = AsyncMock()
        session.commit = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch("spectra_platform.services.mission.state_store.async_session_maker", return_value=session):
            store = MissionStateStore()
            state = await store.get_state("m-1")

        assert state is None
        session.delete.assert_called_once()

    async def test_returns_none_if_not_found(self):
        from spectra_platform.services.mission.state_store import MissionStateStore

        session = AsyncMock()
        session.get = AsyncMock(return_value=None)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch("spectra_platform.services.mission.state_store.async_session_maker", return_value=session):
            store = MissionStateStore()
            state = await store.get_state("m-1")

        assert state is None


@pytest.mark.asyncio
class TestMissionStateStoreGetActive:
    async def test_returns_all_non_expired(self):
        from spectra_platform.services.mission.state_store import MissionStateStore

        entries = [
            _make_cache_entry("mission_state:m-1", {"id": "m-1"}, datetime.now(UTC) + timedelta(hours=1)),
            _make_cache_entry("mission_state:m-2", {"id": "m-2"}, datetime.now(UTC) + timedelta(hours=2)),
        ]

        session = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = entries
        session.execute = AsyncMock(return_value=result)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch("spectra_platform.services.mission.state_store.async_session_maker", return_value=session):
            store = MissionStateStore()
            active = await store.get_active()

        assert len(active) == 2


@pytest.mark.asyncio
class TestMissionStateStoreUnregister:
    async def test_unregister_removes_entry(self):
        from spectra_platform.services.mission.state_store import MissionStateStore

        entry = _make_cache_entry("mission_state:m-1", {})

        session = AsyncMock()
        session.get = AsyncMock(return_value=entry)
        session.delete = AsyncMock()
        session.commit = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch("spectra_platform.services.mission.state_store.async_session_maker", return_value=session):
            store = MissionStateStore()
            await store.unregister("m-1")

        session.delete.assert_called_once_with(entry)

    async def test_unregister_noop_if_missing(self):
        from spectra_platform.services.mission.state_store import MissionStateStore

        session = AsyncMock()
        session.get = AsyncMock(return_value=None)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch("spectra_platform.services.mission.state_store.async_session_maker", return_value=session):
            store = MissionStateStore()
            await store.unregister("nonexistent")
            # Should not raise


@pytest.mark.asyncio
class TestMissionStateStoreCleanup:
    async def test_cleanup_expired(self):
        from spectra_platform.services.mission.state_store import MissionStateStore

        session = AsyncMock()
        exec_result = MagicMock()
        exec_result.rowcount = 3
        session.execute = AsyncMock(return_value=exec_result)
        session.commit = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)

        with patch("spectra_platform.services.mission.state_store.async_session_maker", return_value=session):
            store = MissionStateStore()
            count = await store.cleanup_expired()

        assert count == 3
