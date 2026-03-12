"""Additional repository CRUD tests.

Covers BaseRepository generic methods with a mocked session,
plus verification that AuditLogRepository and UserRepository (not in
the main test_repositories.py) can be instantiated and delegate properly.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.repositories.base import BaseRepository

# ---------------------------------------------------------------------------
# Helpers (mirrors existing pattern from test_repositories)
# ---------------------------------------------------------------------------


def _mock_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    return session


def _mock_model_class(columns=("id", "name", "status")):
    col_attrs = []
    for name in columns:
        attr = MagicMock()
        attr.key = name
        col_attrs.append(attr)
    inspector = MagicMock()
    inspector.mapper.column_attrs = col_attrs
    model = MagicMock()
    model.__name__ = "FakeModel"
    return model, inspector


def _make_base_repo(columns=("id", "name", "status")):
    model, mapper = _mock_model_class(columns)
    session = _mock_session()
    with patch("app.repositories.base.inspect", return_value=mapper):
        repo = BaseRepository(model, session)
    return repo, model, session


# ---------------------------------------------------------------------------
# BaseRepository.create
# ---------------------------------------------------------------------------


class TestBaseRepositoryCreate:
    @pytest.mark.asyncio
    async def test_create_returns_instance(self):
        repo, model, session = _make_base_repo(("id", "name"))
        instance = MagicMock()
        model.return_value = instance
        result = await repo.create(name="hello")
        assert result is instance
        session.add.assert_called_once_with(instance)
        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once_with(instance)

    @pytest.mark.asyncio
    async def test_create_passes_kwargs_to_model(self):
        repo, model, session = _make_base_repo(("id", "name", "status"))
        model.return_value = MagicMock()
        await repo.create(name="a", status="active")
        model.assert_called_once_with(name="a", status="active")


# ---------------------------------------------------------------------------
# BaseRepository.get_by_id
# ---------------------------------------------------------------------------


class TestBaseRepositoryGetById:
    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        repo, _, session = _make_base_repo(("id",))
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute.return_value = result_mock
        with patch("app.repositories.base.select", return_value=MagicMock()):
            result = await repo.get_by_id("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_entity_when_found(self):
        repo, _, session = _make_base_repo(("id",))
        entity = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = entity
        session.execute.return_value = result_mock
        with patch("app.repositories.base.select", return_value=MagicMock()):
            result = await repo.get_by_id("some-id")
        assert result is entity


# ---------------------------------------------------------------------------
# BaseRepository.get_all
# ---------------------------------------------------------------------------


class TestBaseRepositoryGetAll:
    @pytest.mark.asyncio
    async def test_returns_empty_list(self):
        repo, _, session = _make_base_repo(("id",))
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock
        session.execute.return_value = result_mock
        with patch("app.repositories.base.select", return_value=MagicMock()):
            result = await repo.get_all()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_paginated_results(self):
        repo, _, session = _make_base_repo(("id",))
        entities = [MagicMock(), MagicMock()]
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = entities
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock
        session.execute.return_value = result_mock
        with patch("app.repositories.base.select", return_value=MagicMock()):
            result = await repo.get_all(skip=0, limit=2)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# BaseRepository.update
# ---------------------------------------------------------------------------


class TestBaseRepositoryUpdate:
    @pytest.mark.asyncio
    async def test_update_returns_entity(self):
        repo, _, session = _make_base_repo(("id", "name"))
        entity = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = entity
        session.execute.return_value = result_mock
        with patch("app.repositories.base.update", return_value=MagicMock()):
            result = await repo.update("some-id", name="new")
        assert result is entity
        session.flush.assert_awaited()

    @pytest.mark.asyncio
    async def test_update_returns_none_when_missing(self):
        repo, _, session = _make_base_repo(("id", "name"))
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute.return_value = result_mock
        with patch("app.repositories.base.update", return_value=MagicMock()):
            result = await repo.update("missing-id", name="x")
        assert result is None


# ---------------------------------------------------------------------------
# BaseRepository.delete
# ---------------------------------------------------------------------------


class TestBaseRepositoryDelete:
    @pytest.mark.asyncio
    async def test_delete_true_when_found(self):
        repo, _, session = _make_base_repo(("id",))
        result_mock = MagicMock()
        result_mock.rowcount = 1
        session.execute.return_value = result_mock
        with patch("app.repositories.base.delete", return_value=MagicMock()):
            assert await repo.delete("id-1") is True

    @pytest.mark.asyncio
    async def test_delete_false_when_missing(self):
        repo, _, session = _make_base_repo(("id",))
        result_mock = MagicMock()
        result_mock.rowcount = 0
        session.execute.return_value = result_mock
        with patch("app.repositories.base.delete", return_value=MagicMock()):
            assert await repo.delete("id-x") is False


# ---------------------------------------------------------------------------
# BaseRepository.find_one_by / find_many_by
# ---------------------------------------------------------------------------


class TestBaseRepositoryFinders:
    @pytest.mark.asyncio
    async def test_find_one_by_validates(self):
        repo, _, _ = _make_base_repo(("id", "name"))
        with pytest.raises(ValueError, match="Invalid filter field"):
            await repo.find_one_by(nonexistent="x")

    @pytest.mark.asyncio
    async def test_find_many_by_validates(self):
        repo, _, _ = _make_base_repo(("id", "name"))
        with pytest.raises(ValueError, match="Invalid filter field"):
            await repo.find_many_by(nonexistent="x")

    @pytest.mark.asyncio
    async def test_find_one_by_returns_entity(self):
        repo, _, session = _make_base_repo(("id", "name"))
        entity = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = entity
        session.execute.return_value = result_mock
        with patch("app.repositories.base.select", return_value=MagicMock()):
            result = await repo.find_one_by(name="test")
        assert result is entity

    @pytest.mark.asyncio
    async def test_find_many_by_returns_list(self):
        repo, _, session = _make_base_repo(("id", "name"))
        entities = [MagicMock()]
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = entities
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock
        session.execute.return_value = result_mock
        with patch("app.repositories.base.select", return_value=MagicMock()):
            result = await repo.find_many_by(name="test")
        assert result == entities


# ---------------------------------------------------------------------------
# BaseRepository.count
# ---------------------------------------------------------------------------


class TestBaseRepositoryCount:
    @pytest.mark.asyncio
    async def test_count_no_filters(self):
        repo, _, session = _make_base_repo(("id",))
        result_mock = MagicMock()
        result_mock.scalar_one.return_value = 42
        session.execute.return_value = result_mock
        with patch("app.repositories.base.select", return_value=MagicMock()):
            result = await repo.count()
        assert result == 42

    @pytest.mark.asyncio
    async def test_count_with_invalid_filter_raises(self):
        repo, _, _ = _make_base_repo(("id",))
        with pytest.raises(ValueError, match="Invalid filter field"):
            await repo.count(bad="value")


# ---------------------------------------------------------------------------
# AuditLogRepository
# ---------------------------------------------------------------------------


class TestAuditLogRepository:
    def test_instantiation(self):
        from app.repositories.audit_log import AuditLogRepository

        session = _mock_session()
        with patch("app.repositories.base.inspect") as mock_inspect:
            mock_inspect.return_value = MagicMock(mapper=MagicMock(column_attrs=[]))
            repo = AuditLogRepository(session)
        assert repo.session is session
        assert issubclass(AuditLogRepository, BaseRepository)

    @pytest.mark.asyncio
    async def test_list_events(self):
        from app.repositories.audit_log import AuditLogRepository

        session = _mock_session()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = ["log1", "log2"]
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock
        session.execute.return_value = result_mock

        with patch("app.repositories.base.inspect") as mock_inspect:
            mock_inspect.return_value = MagicMock(mapper=MagicMock(column_attrs=[]))
            repo = AuditLogRepository(session)
        events = await repo.list_events(skip=0, limit=10)
        assert events == ["log1", "log2"]


# ---------------------------------------------------------------------------
# UserRepository
# ---------------------------------------------------------------------------


class TestUserRepository:
    def test_instantiation(self):
        from app.repositories.user import UserRepository

        session = _mock_session()
        with patch("app.repositories.base.inspect") as mock_inspect:
            mock_inspect.return_value = MagicMock(mapper=MagicMock(column_attrs=[]))
            repo = UserRepository(session)
        assert repo.session is session
        assert issubclass(UserRepository, BaseRepository)

    @pytest.mark.asyncio
    async def test_get_by_username_delegates(self):
        from app.repositories.user import UserRepository

        session = _mock_session()
        with patch("app.repositories.base.inspect") as mock_inspect:
            mock_inspect.return_value = MagicMock(mapper=MagicMock(column_attrs=[]))
            repo = UserRepository(session)
        with patch.object(repo, "find_one_by", new_callable=AsyncMock, return_value="user1") as mock:
            result = await repo.get_by_username("admin")
            mock.assert_awaited_once_with(username="admin")
        assert result == "user1"

    @pytest.mark.asyncio
    async def test_get_by_email_delegates(self):
        from app.repositories.user import UserRepository

        session = _mock_session()
        with patch("app.repositories.base.inspect") as mock_inspect:
            mock_inspect.return_value = MagicMock(mapper=MagicMock(column_attrs=[]))
            repo = UserRepository(session)
        with patch.object(repo, "find_one_by", new_callable=AsyncMock, return_value="user2") as mock:
            result = await repo.get_by_email("a@b.com")
            mock.assert_awaited_once_with(email="a@b.com")
        assert result == "user2"

    @pytest.mark.asyncio
    async def test_get_active_users_delegates(self):
        from app.repositories.user import UserRepository

        session = _mock_session()
        with patch("app.repositories.base.inspect") as mock_inspect:
            mock_inspect.return_value = MagicMock(mapper=MagicMock(column_attrs=[]))
            repo = UserRepository(session)
        with patch.object(repo, "find_many_by", new_callable=AsyncMock, return_value=["u1"]) as mock:
            result = await repo.get_active_users(skip=0, limit=50)
            mock.assert_awaited_once_with(is_active=True, skip=0, limit=50)
        assert result == ["u1"]

    @pytest.mark.asyncio
    async def test_get_superusers_delegates(self):
        from app.repositories.user import UserRepository

        session = _mock_session()
        with patch("app.repositories.base.inspect") as mock_inspect:
            mock_inspect.return_value = MagicMock(mapper=MagicMock(column_attrs=[]))
            repo = UserRepository(session)
        with patch.object(repo, "find_many_by", new_callable=AsyncMock, return_value=[]) as mock:
            result = await repo.get_superusers()
            mock.assert_awaited_once_with(is_superuser=True)
        assert result == []


# ---------------------------------------------------------------------------
# TargetRepository
# ---------------------------------------------------------------------------


class TestTargetRepositoryCrud:
    @pytest.mark.asyncio
    async def test_find_by_address_delegates(self):
        from app.repositories.target import TargetRepository

        session = _mock_session()
        with patch("app.repositories.base.inspect") as mock_inspect:
            mock_inspect.return_value = MagicMock(mapper=MagicMock(column_attrs=[]))
            repo = TargetRepository(session)
        with patch.object(repo, "find_one_by", new_callable=AsyncMock, return_value="target1") as mock:
            result = await repo.find_by_address("10.0.0.1")
            mock.assert_awaited_once_with(address="10.0.0.1")
        assert result == "target1"

    @pytest.mark.asyncio
    async def test_find_by_address_with_user_id(self):
        from app.repositories.target import TargetRepository

        session = _mock_session()
        with patch("app.repositories.base.inspect") as mock_inspect:
            mock_inspect.return_value = MagicMock(mapper=MagicMock(column_attrs=[]))
            repo = TargetRepository(session)
        with patch.object(repo, "find_one_by", new_callable=AsyncMock, return_value=None) as mock:
            await repo.find_by_address("10.0.0.1", user_id="u-1")
            mock.assert_awaited_once_with(address="10.0.0.1", user_id="u-1")

    @pytest.mark.asyncio
    async def test_update_status_delegates(self):
        from app.repositories.target import TargetRepository

        session = _mock_session()
        with patch("app.repositories.base.inspect") as mock_inspect:
            mock_inspect.return_value = MagicMock(mapper=MagicMock(column_attrs=[]))
            repo = TargetRepository(session)
        with patch.object(repo, "update", new_callable=AsyncMock, return_value="updated") as mock:
            result = await repo.update_status("t-1", "scanning")
            mock.assert_awaited_once_with("t-1", status="scanning")
        assert result == "updated"


# ---------------------------------------------------------------------------
# MissionRepository
# ---------------------------------------------------------------------------


class TestMissionRepositoryCrud:
    def test_instantiation(self):
        from app.repositories.mission import MissionRepository

        session = _mock_session()
        with patch("app.repositories.base.inspect") as mock_inspect:
            mock_inspect.return_value = MagicMock(mapper=MagicMock(column_attrs=[]))
            repo = MissionRepository(session)
        assert issubclass(MissionRepository, BaseRepository)
        assert repo.session is session


# ---------------------------------------------------------------------------
# ExploitRepository
# ---------------------------------------------------------------------------


class TestExploitRepositoryCrud:
    def test_instantiation(self):
        from app.repositories.exploit import ExploitRepository

        session = _mock_session()
        with patch("app.repositories.base.inspect") as mock_inspect:
            mock_inspect.return_value = MagicMock(mapper=MagicMock(column_attrs=[]))
            repo = ExploitRepository(session)
        assert issubclass(ExploitRepository, BaseRepository)
        assert repo.session is session


# ---------------------------------------------------------------------------
# FindingRepository
# ---------------------------------------------------------------------------


class TestFindingRepositoryCrud:
    def test_instantiation(self):
        from app.repositories.finding import FindingRepository

        session = _mock_session()
        with patch("app.repositories.base.inspect") as mock_inspect:
            mock_inspect.return_value = MagicMock(mapper=MagicMock(column_attrs=[]))
            repo = FindingRepository(session)
        assert issubclass(FindingRepository, BaseRepository)
        assert repo.session is session


# ---------------------------------------------------------------------------
# PentestSessionRepository
# ---------------------------------------------------------------------------


class TestPentestSessionRepositoryCrud:
    def test_instantiation(self):
        from app.repositories.pentest_session import PentestSessionRepository

        session = _mock_session()
        with patch("app.repositories.base.inspect") as mock_inspect:
            mock_inspect.return_value = MagicMock(mapper=MagicMock(column_attrs=[]))
            repo = PentestSessionRepository(session)
        assert issubclass(PentestSessionRepository, BaseRepository)
        assert repo.session is session
