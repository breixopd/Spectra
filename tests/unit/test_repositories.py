"""Tests for repository CRUD operations.

Tests PlanRepository, SubscriptionRepository, ApiKeyRepository,
ServerNodeRepository, and SystemConfigRepository using mocked
AsyncSession to verify query construction and delegation.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.repositories.api_key import ApiKeyRepository
from app.repositories.plan import PlanRepository
from app.repositories.server_node import ServerNodeRepository
from app.repositories.subscription import SubscriptionRepository
from app.repositories.system_config import SystemConfigRepository


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
        with patch.object(repo, "get_by_key", new_callable=AsyncMock, return_value=None), \
             patch.object(repo, "create", new_callable=AsyncMock, return_value="new-cfg") as mock_create:
            result = await repo.upsert("NEW_KEY", "value1", is_secret=False)
            mock_create.assert_awaited_once_with(key="NEW_KEY", value="value1", is_secret=False)
        assert result == "new-cfg"

    @pytest.mark.asyncio
    async def test_upsert_updates_when_existing(self):
        session = _mock_session()
        repo = SystemConfigRepository(session)
        existing = MagicMock()
        existing.id = "cfg-id-1"
        with patch.object(repo, "get_by_key", new_callable=AsyncMock, return_value=existing), \
             patch.object(repo, "update", new_callable=AsyncMock, return_value="updated-cfg") as mock_update:
            result = await repo.upsert("EXISTING", "new-val", is_secret=True)
            mock_update.assert_awaited_once_with("cfg-id-1", value="new-val", is_secret=True)
        assert result == "updated-cfg"
