"""Tests for repository CRUD operations.

Tests PlanRepository, SubscriptionRepository, ApiKeyRepository,
ServerNodeRepository, SystemConfigRepository, BaseRepository, and
all concrete repository classes.
"""

import inspect as _inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.repositories import (
    ApiKeyRepository,
    BaseRepository,
    ExploitRepository,
    FindingRepository,
    MissionRepository,
    PentestSessionRepository,
    PlanRepository,
    ServerNodeRepository,
    SubscriptionRepository,
    SystemConfigRepository,
    TargetRepository,
    UserRepository,
)


def _mock_session():
    """Build a minimal mocked AsyncSession."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    return session


# ---------------------------------------------------------------------------
# PlanRepository
# ---------------------------------------------------------------------------


class TestPlanRepository:
    @pytest.mark.asyncio
    async def test_get_by_name_delegates(self):
        session = _mock_session()
        repo = PlanRepository(session)
        with patch.object(repo, "find_one_by", new_callable=AsyncMock, return_value=None) as mock:
            result = await repo.get_by_name("free")
            mock.assert_awaited_once_with(name="free")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_active_plans(self):
        session = _mock_session()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = ["plan1", "plan2"]
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock
        session.execute.return_value = result_mock

        repo = PlanRepository(session)
        plans = await repo.get_active_plans(skip=0, limit=10)
        assert plans == ["plan1", "plan2"]
        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_default_plan_delegates(self):
        session = _mock_session()
        repo = PlanRepository(session)
        with patch.object(repo, "find_one_by", new_callable=AsyncMock, return_value="default") as mock:
            result = await repo.get_default_plan()
            mock.assert_awaited_once_with(is_default=True)
        assert result == "default"


# ---------------------------------------------------------------------------
# SubscriptionRepository
# ---------------------------------------------------------------------------


class TestSubscriptionRepository:
    @pytest.mark.asyncio
    async def test_get_by_user_id(self):
        session = _mock_session()
        repo = SubscriptionRepository(session)
        with patch.object(repo, "find_one_by", new_callable=AsyncMock, return_value="sub1") as mock:
            result = await repo.get_by_user_id("user-1")
            mock.assert_awaited_once_with(user_id="user-1")
        assert result == "sub1"

    @pytest.mark.asyncio
    async def test_get_active_by_user(self):
        session = _mock_session()
        repo = SubscriptionRepository(session)
        with patch.object(repo, "find_one_by", new_callable=AsyncMock, return_value=None) as mock:
            result = await repo.get_active_by_user("user-2")
            mock.assert_awaited_once_with(user_id="user-2", status="active")
        assert result is None


# ---------------------------------------------------------------------------
# ApiKeyRepository
# ---------------------------------------------------------------------------


class TestApiKeyRepository:
    @pytest.mark.asyncio
    async def test_get_by_user_id(self):
        session = _mock_session()
        repo = ApiKeyRepository(session)
        with patch.object(repo, "find_many_by", new_callable=AsyncMock, return_value=[]) as mock:
            result = await repo.get_by_user_id("u1", skip=0, limit=50)
            mock.assert_awaited_once_with(user_id="u1", skip=0, limit=50)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_by_prefix(self):
        session = _mock_session()
        repo = ApiKeyRepository(session)
        with patch.object(repo, "find_one_by", new_callable=AsyncMock, return_value="key-obj") as mock:
            result = await repo.get_by_prefix("sk_live_abc")
            mock.assert_awaited_once_with(key_prefix="sk_live_abc")
        assert result == "key-obj"

    @pytest.mark.asyncio
    async def test_get_active_by_user(self):
        session = _mock_session()
        repo = ApiKeyRepository(session)
        with patch.object(repo, "find_many_by", new_callable=AsyncMock, return_value=["k1"]) as mock:
            result = await repo.get_active_by_user("u2")
            mock.assert_awaited_once_with(user_id="u2", is_active=True, skip=0, limit=100)
        assert result == ["k1"]

    @pytest.mark.asyncio
    async def test_deactivate(self):
        session = _mock_session()
        repo = ApiKeyRepository(session)
        with patch.object(repo, "update", new_callable=AsyncMock, return_value="updated") as mock:
            result = await repo.deactivate("key-id")
            mock.assert_awaited_once_with("key-id", is_active=False)
        assert result == "updated"


# ---------------------------------------------------------------------------
# ServerNodeRepository
# ---------------------------------------------------------------------------


class TestServerNodeRepository:
    @pytest.mark.asyncio
    async def test_get_by_service_type(self):
        session = _mock_session()
        repo = ServerNodeRepository(session)
        with patch.object(repo, "find_many_by", new_callable=AsyncMock, return_value=["n1"]) as mock:
            result = await repo.get_by_service_type("llm")
            mock.assert_awaited_once_with(service_type="llm", skip=0, limit=100)
        assert result == ["n1"]

    @pytest.mark.asyncio
    async def test_get_active_nodes(self):
        session = _mock_session()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = ["active-node"]
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock
        session.execute.return_value = result_mock

        repo = ServerNodeRepository(session)
        nodes = await repo.get_active_nodes(service_type="sandbox")
        assert nodes == ["active-node"]

    @pytest.mark.asyncio
    async def test_get_active_nodes_no_filter(self):
        session = _mock_session()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock
        session.execute.return_value = result_mock

        repo = ServerNodeRepository(session)
        nodes = await repo.get_active_nodes()
        assert nodes == []

    @pytest.mark.asyncio
    async def test_get_primary_node(self):
        session = _mock_session()
        repo = ServerNodeRepository(session)
        with patch.object(repo, "find_one_by", new_callable=AsyncMock, return_value="primary") as mock:
            result = await repo.get_primary_node("llm")
            mock.assert_awaited_once_with(service_type="llm", is_primary=True)
        assert result == "primary"


# ---------------------------------------------------------------------------
# SystemConfigRepository
# ---------------------------------------------------------------------------


class TestSystemConfigRepository:
    @pytest.mark.asyncio
    async def test_get_by_key(self):
        session = _mock_session()
        repo = SystemConfigRepository(session)
        with patch.object(repo, "find_one_by", new_callable=AsyncMock, return_value="cfg") as mock:
            result = await repo.get_by_key("LOG_LEVEL")
            mock.assert_awaited_once_with(key="LOG_LEVEL")
        assert result == "cfg"

    @pytest.mark.asyncio
    async def test_get_all_non_secret(self):
        session = _mock_session()
        repo = SystemConfigRepository(session)
        with patch.object(repo, "find_many_by", new_callable=AsyncMock, return_value=["c1"]) as mock:
            result = await repo.get_all_non_secret()
            mock.assert_awaited_once_with(is_secret=False, limit=1000)
        assert result == ["c1"]

    @pytest.mark.asyncio
    async def test_upsert_creates_when_not_existing(self):
        session = _mock_session()
        repo = SystemConfigRepository(session)
        with (
            patch.object(repo, "get_by_key", new_callable=AsyncMock, return_value=None),
            patch.object(repo, "create", new_callable=AsyncMock, return_value="new-cfg") as mock_create,
        ):
            result = await repo.upsert("NEW_KEY", "value1", is_secret=False)
            mock_create.assert_awaited_once_with(key="NEW_KEY", value="value1", is_secret=False)
        assert result == "new-cfg"

    @pytest.mark.asyncio
    async def test_upsert_updates_when_existing(self):
        session = _mock_session()
        repo = SystemConfigRepository(session)
        existing = MagicMock()
        existing.id = "cfg-id-1"
        with (
            patch.object(repo, "get_by_key", new_callable=AsyncMock, return_value=existing),
            patch.object(repo, "update", new_callable=AsyncMock, return_value="updated-cfg") as mock_update,
        ):
            result = await repo.upsert("EXISTING", "new-val", is_secret=True)
            mock_update.assert_awaited_once_with("cfg-id-1", value="new-val", is_secret=True)
        assert result == "updated-cfg"


# ---------------------------------------------------------------------------
# Helpers for BaseRepository tests
# ---------------------------------------------------------------------------


def _mock_model_class(columns=("id", "created_at", "updated_at")):
    """Return a fake model class whose mapper exposes the given column names."""
    col_attrs = []
    for name in columns:
        attr = MagicMock()
        attr.key = name
        col_attrs.append(attr)
    # inspect(model) returns an inspector; code accesses .mapper.column_attrs
    inspector = MagicMock()
    inspector.mapper.column_attrs = col_attrs
    model = MagicMock()
    model.__name__ = "FakeModel"
    return model, inspector


# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------


class TestRepositoryImports:
    """All repository classes can be imported from the package."""

    def test_base_repository_importable(self):
        assert BaseRepository is not None

    def test_all_repositories_importable(self):
        repos = [
            ApiKeyRepository,
            ExploitRepository,
            FindingRepository,
            MissionRepository,
            PentestSessionRepository,
            PlanRepository,
            ServerNodeRepository,
            SubscriptionRepository,
            SystemConfigRepository,
            TargetRepository,
            UserRepository,
        ]
        for repo_cls in repos:
            assert repo_cls is not None
            assert issubclass(repo_cls, BaseRepository)


# ---------------------------------------------------------------------------
# BaseRepository._validate_filters
# ---------------------------------------------------------------------------


def _make_base_repo(columns=("id", "name", "status")):
    """Build a BaseRepository with a mocked model and patched inspect."""
    model, mapper = _mock_model_class(columns)
    session = _mock_session()
    with patch("app.repositories.base.inspect", return_value=mapper):
        repo = BaseRepository(model, session)  # type: ignore[arg-type]
    return repo, model, session


class TestBaseRepositoryValidateFilters:
    """Test _validate_filters without touching the database."""

    def test_valid_filter_accepted(self):
        repo, _, _ = _make_base_repo()
        repo._validate_filters({"name": "x", "status": "active"})

    def test_invalid_filter_raises(self):
        repo, _, _ = _make_base_repo()
        with pytest.raises(ValueError, match="Invalid filter field"):
            repo._validate_filters({"nonexistent": "value"})

    def test_empty_filters_accepted(self):
        repo, _, _ = _make_base_repo()
        repo._validate_filters({})

    def test_allowed_filters_derived_from_model(self):
        repo, _, _ = _make_base_repo(("id", "foo", "bar"))
        assert repo._allowed_filters == {"id", "foo", "bar"}


# ---------------------------------------------------------------------------
# BaseRepository attributes
# ---------------------------------------------------------------------------


class TestBaseRepositoryAttributes:
    def test_model_and_session_stored(self):
        repo, model, session = _make_base_repo()
        assert repo.model is model
        assert repo.session is session


# ---------------------------------------------------------------------------
# BaseRepository async CRUD (mocked session)
# ---------------------------------------------------------------------------


class TestBaseRepositoryCRUD:
    """Test CRUD methods — patch SA statement constructors to avoid model validation."""

    @pytest.mark.asyncio
    async def test_create_adds_and_flushes(self):
        repo, model, session = _make_base_repo(("id", "name"))
        instance = MagicMock()
        model.return_value = instance
        await repo.create(name="test")
        session.add.assert_called_once_with(instance)
        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once_with(instance)

    @pytest.mark.asyncio
    async def test_get_by_id_executes_select(self):
        repo, _, session = _make_base_repo(("id", "name"))
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute.return_value = result_mock
        with patch("app.repositories.base.select", return_value=MagicMock()):
            result = await repo.get_by_id("some-uuid")
        session.execute.assert_awaited_once()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_executes_select(self):
        repo, _, session = _make_base_repo(("id", "name"))
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock
        session.execute.return_value = result_mock
        with patch("app.repositories.base.select", return_value=MagicMock()):
            result = await repo.get_all(skip=0, limit=10)
        session.execute.assert_awaited_once()
        assert result == []

    @pytest.mark.asyncio
    async def test_delete_returns_true(self):
        repo, _, session = _make_base_repo(("id", "name"))
        result_mock = MagicMock()
        result_mock.rowcount = 1
        session.execute.return_value = result_mock
        with patch("app.repositories.base.delete", return_value=MagicMock()):
            assert await repo.delete("some-uuid") is True

    @pytest.mark.asyncio
    async def test_delete_returns_false_when_not_found(self):
        repo, _, session = _make_base_repo(("id", "name"))
        result_mock = MagicMock()
        result_mock.rowcount = 0
        session.execute.return_value = result_mock
        with patch("app.repositories.base.delete", return_value=MagicMock()):
            assert await repo.delete("missing-uuid") is False

    @pytest.mark.asyncio
    async def test_find_one_by_validates_filters(self):
        repo, _, _ = _make_base_repo(("id", "name"))
        with pytest.raises(ValueError, match="Invalid filter field"):
            await repo.find_one_by(bad_column="x")

    @pytest.mark.asyncio
    async def test_find_many_by_validates_filters(self):
        repo, _, _ = _make_base_repo(("id", "name"))
        with pytest.raises(ValueError, match="Invalid filter field"):
            await repo.find_many_by(bad_column="x")

    @pytest.mark.asyncio
    async def test_count_validates_filters(self):
        repo, _, _ = _make_base_repo(("id", "name"))
        with pytest.raises(ValueError, match="Invalid filter field"):
            await repo.count(bad_column="x")

    @pytest.mark.asyncio
    async def test_update_executes_and_flushes(self):
        repo, _, session = _make_base_repo(("id", "name"))
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = MagicMock()
        session.execute.return_value = result_mock
        with patch("app.repositories.base.update", return_value=MagicMock()):
            result = await repo.update("some-uuid", name="new_name")
        session.execute.assert_awaited_once()
        session.flush.assert_awaited_once()
        assert result is not None


# ---------------------------------------------------------------------------
# Concrete repository subclass checks
# ---------------------------------------------------------------------------


_ALL_CONCRETE_REPOS = [
    ApiKeyRepository,
    ExploitRepository,
    FindingRepository,
    MissionRepository,
    PentestSessionRepository,
    PlanRepository,
    ServerNodeRepository,
    SubscriptionRepository,
    SystemConfigRepository,
    TargetRepository,
    UserRepository,
]


class TestConcreteRepositories:
    @pytest.mark.parametrize("repo_cls", _ALL_CONCRETE_REPOS)
    def test_is_subclass_of_base(self, repo_cls):
        assert issubclass(repo_cls, BaseRepository)

    @pytest.mark.parametrize("repo_cls", _ALL_CONCRETE_REPOS)
    def test_init_accepts_session(self, repo_cls):
        sig = _inspect.signature(repo_cls.__init__)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "session" in params
