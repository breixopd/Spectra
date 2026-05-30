"""Tests for ServerPoolManager — server pool scaling and load balancing."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mock_node(**overrides):
    """Create a mock ServerNode with sensible defaults."""
    defaults = {
        "id": 1,
        "service_type": "sandbox_worker",
        "name": "worker-1",
        "url": "http://worker1:8080",
        "api_key": None,
        "is_active": True,
        "is_primary": False,
        "weight": 1,
        "max_capacity": 10,
        "current_load": 0,
        "health_status": "healthy",
        "last_health_check": None,
        "last_error": None,
        "metadata_": None,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    node = MagicMock()
    for k, v in defaults.items():
        setattr(node, k, v)
    node.to_dict.return_value = {k: v for k, v in defaults.items() if k != "metadata_" and k != "updated_at"}
    node.to_dict.return_value["metadata"] = defaults.get("metadata_")
    return node


class TestServerPoolManagerInit:
    """Basic init and import."""

    def test_import(self):
        from spectra_scaling.pool_manager import ServerPoolManager

        assert ServerPoolManager is not None

    def test_init(self):
        from spectra_scaling.pool_manager import ServerPoolManager

        mgr = ServerPoolManager()
        assert mgr._health_task is None
        assert mgr._health_interval == 30


class TestAddNode:
    """add_node creates a node record."""

    @pytest.mark.asyncio
    async def test_add_node_creates_node(self):
        from spectra_scaling.pool_manager import ServerPoolManager

        mgr = ServerPoolManager()
        session = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()

        mock_instance = _make_mock_node(name="new-worker")

        with (
            patch("spectra_persistence.models.server_node.ServerNode", return_value=mock_instance),
            patch.object(
                ServerPoolManager,
                "_auto_enable_autoscale",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await mgr.add_node(
                session,
                "sandbox_worker",
                "new-worker",
                "http://new:8080",
                weight=2,
                max_capacity=5,
            )

        session.add.assert_called_once()
        session.flush.assert_awaited_once()
        assert result["name"] == "new-worker"


class TestRemoveNode:
    """remove_node returns True/False."""

    @pytest.mark.asyncio
    async def test_remove_existing_node(self):
        from spectra_scaling.pool_manager import ServerPoolManager

        mgr = ServerPoolManager()
        session = AsyncMock()
        mock_node = _make_mock_node(id=42)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_node
        session.execute = AsyncMock(return_value=mock_result)
        session.delete = AsyncMock()

        result = await mgr.remove_node(session, 42)
        assert result is True
        session.delete.assert_awaited_once_with(mock_node)

    @pytest.mark.asyncio
    async def test_remove_nonexistent_node(self):
        from spectra_scaling.pool_manager import ServerPoolManager

        mgr = ServerPoolManager()
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        result = await mgr.remove_node(session, 999)
        assert result is False


class TestListNodes:
    """list_nodes with/without filters."""

    @pytest.mark.asyncio
    async def test_list_all_nodes(self):
        from spectra_scaling.pool_manager import ServerPoolManager

        mgr = ServerPoolManager()
        session = AsyncMock()
        mock_nodes = [_make_mock_node(id=1), _make_mock_node(id=2, name="worker-2")]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_nodes
        session.execute = AsyncMock(return_value=mock_result)

        nodes = await mgr.list_nodes(session)
        assert len(nodes) == 2

    @pytest.mark.asyncio
    async def test_list_nodes_with_filter(self):
        from spectra_scaling.pool_manager import ServerPoolManager

        mgr = ServerPoolManager()
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [_make_mock_node()]
        session.execute = AsyncMock(return_value=mock_result)

        nodes = await mgr.list_nodes(session, service_type="sandbox_worker")
        assert len(nodes) == 1


class TestSelectNode:
    """select_node weighted least-connections algorithm."""

    @pytest.mark.asyncio
    async def test_select_node_returns_best(self):
        from spectra_scaling.pool_manager import ServerPoolManager

        mgr = ServerPoolManager()
        node1 = _make_mock_node(
            id=1,
            weight=1,
            current_load=5,
            max_capacity=10,
            health_status="healthy",
            is_active=True,
            service_type="sandbox_worker",
        )
        node2 = _make_mock_node(
            id=2,
            weight=2,
            current_load=2,
            max_capacity=10,
            health_status="healthy",
            is_active=True,
            service_type="sandbox_worker",
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [node1, node2]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("spectra_scaling.pool_manager.async_session_maker", return_value=mock_session_ctx):
            result = await mgr.select_node("sandbox_worker")

        # node2 has lower load/weight ratio (2/2=1) vs node1 (5/1=5)
        assert result is not None

    @pytest.mark.asyncio
    async def test_select_node_returns_none_when_empty(self):
        from spectra_scaling.pool_manager import ServerPoolManager

        mgr = ServerPoolManager()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("spectra_scaling.pool_manager.async_session_maker", return_value=mock_session_ctx):
            result = await mgr.select_node("sandbox_worker")
        assert result is None


class TestLoadManagement:
    """increment_load / decrement_load."""

    @pytest.mark.asyncio
    async def test_increment_load(self):
        from spectra_scaling.pool_manager import ServerPoolManager

        mgr = ServerPoolManager()
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("spectra_scaling.pool_manager.async_session_maker", return_value=mock_session_ctx):
            await mgr.increment_load(1)

        mock_session.execute.assert_awaited_once()
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_decrement_load(self):
        from spectra_scaling.pool_manager import ServerPoolManager

        mgr = ServerPoolManager()
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("spectra_scaling.pool_manager.async_session_maker", return_value=mock_session_ctx):
            await mgr.decrement_load(1)

        mock_session.execute.assert_awaited_once()
        mock_session.commit.assert_awaited_once()


class TestHealthCheck:
    """Health check operations."""

    @pytest.mark.asyncio
    async def test_health_check_node_healthy(self):
        from spectra_scaling.pool_manager import ServerPoolManager

        mgr = ServerPoolManager()
        node = {"url": "http://worker:8080", "id": 1}

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client_ctx = AsyncMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client_ctx):
            result = await mgr.health_check_node(node)
        assert result["health_status"] == "healthy"
        assert result["last_error"] is None

    @pytest.mark.asyncio
    async def test_health_check_node_unhealthy_status(self):
        from spectra_scaling.pool_manager import ServerPoolManager

        mgr = ServerPoolManager()
        node = {"url": "http://worker:8080", "id": 1}

        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client_ctx = AsyncMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client_ctx):
            result = await mgr.health_check_node(node)
        assert result["health_status"] == "unhealthy"
        assert "503" in result["last_error"]

    @pytest.mark.asyncio
    async def test_health_check_node_connection_error(self):
        from spectra_scaling.pool_manager import ServerPoolManager

        mgr = ServerPoolManager()
        node = {"url": "http://worker:8080", "id": 1}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=ConnectionError("refused"))
        mock_client_ctx = AsyncMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client_ctx):
            result = await mgr.health_check_node(node)
        assert result["health_status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_health_check_all(self):
        from spectra_scaling.pool_manager import ServerPoolManager

        mgr = ServerPoolManager()
        mock_node = _make_mock_node(service_type="sandbox_worker")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_node]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("spectra_scaling.pool_manager.async_session_maker", return_value=mock_session_ctx):
            with patch.object(mgr, "health_check_node", new_callable=AsyncMock) as mock_hc:
                mock_hc.return_value = {"health_status": "healthy", "last_error": None}
                with patch.object(mgr, "_collect_node_metrics", new_callable=AsyncMock) as mock_nm:
                    mock_nm.return_value = None
                    results = await mgr.health_check_all()

        assert "sandbox_worker" in results
        assert len(results["sandbox_worker"]) == 1


class TestHealthLoop:
    """Start/stop health loop."""

    @pytest.mark.asyncio
    async def test_start_health_loop_creates_task(self):
        from spectra_scaling.pool_manager import ServerPoolManager

        mgr = ServerPoolManager()

        with patch.object(mgr, "health_check_all", new_callable=AsyncMock):
            await mgr.start_health_loop()
            assert mgr._health_task is not None
            # Clean up
            await mgr.stop_health_loop()
            assert mgr._health_task is None

    @pytest.mark.asyncio
    async def test_stop_health_loop_cancels_task(self):
        from spectra_scaling.pool_manager import ServerPoolManager

        mgr = ServerPoolManager()
        mock_task = MagicMock()
        mgr._health_task = mock_task

        await mgr.stop_health_loop()
        mock_task.cancel.assert_called_once()
        assert mgr._health_task is None

    @pytest.mark.asyncio
    async def test_stop_health_loop_noop_when_none(self):
        from spectra_scaling.pool_manager import ServerPoolManager

        mgr = ServerPoolManager()
        mgr._health_task = None
        await mgr.stop_health_loop()  # should not raise


class TestGetPoolManager:
    """Singleton accessor."""

    def test_get_pool_manager_creates_singleton(self):
        import spectra_scaling.pool_manager as mod

        mod._pool_manager = None
        mgr = mod.get_pool_manager()
        assert mgr is not None
        mgr2 = mod.get_pool_manager()
        assert mgr is mgr2
        mod._pool_manager = None  # cleanup


class TestGetNode:
    """get_node returns single node."""

    @pytest.mark.asyncio
    async def test_get_node_found(self):
        from spectra_scaling.pool_manager import ServerPoolManager

        mgr = ServerPoolManager()
        session = AsyncMock()
        mock_node = _make_mock_node(id=1)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_node
        session.execute = AsyncMock(return_value=mock_result)

        result = await mgr.get_node(session, 1)
        assert result is not None

    @pytest.mark.asyncio
    async def test_get_node_not_found(self):
        from spectra_scaling.pool_manager import ServerPoolManager

        mgr = ServerPoolManager()
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        result = await mgr.get_node(session, 999)
        assert result is None


class TestUpdateNode:
    """update_node modifies fields."""

    @pytest.mark.asyncio
    async def test_update_existing_node(self):
        from spectra_scaling.pool_manager import ServerPoolManager

        mgr = ServerPoolManager()
        session = AsyncMock()
        mock_node = _make_mock_node(id=1, weight=1)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_node
        session.execute = AsyncMock(return_value=mock_result)
        session.flush = AsyncMock()

        result = await mgr.update_node(session, 1, weight=5)
        assert result is not None
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_nonexistent_node(self):
        from spectra_scaling.pool_manager import ServerPoolManager

        mgr = ServerPoolManager()
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        result = await mgr.update_node(session, 999, weight=5)
        assert result is None
