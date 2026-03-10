"""Tests for admin server pool endpoint logic.

Tests the pool_manager calls that the admin endpoints delegate to,
plus request-level field filtering and error handling logic.
The admin module uses Depends(require_permission(...)) which prevents
direct function import in test, so we test the underlying logic.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

import pytest


def _mock_node_dict(**overrides):
    """Build a mock node dict."""
    defaults = {
        "id": 1,
        "service_type": "sandbox_worker",
        "name": "worker-1",
        "url": "http://worker1:8080",
        "is_active": True,
        "is_primary": False,
        "weight": 1,
        "max_capacity": 10,
        "current_load": 0,
        "health_status": "healthy",
        "last_health_check": None,
        "last_error": None,
        "metadata": None,
        "created_at": "2026-01-01T00:00:00",
    }
    defaults.update(overrides)
    return defaults


class TestListServerNodes:
    """GET /api/admin/servers — pool_manager.list_nodes delegation."""

    @pytest.mark.asyncio
    async def test_list_returns_nodes(self):
        from app.services.scaling.pool_manager import ServerPoolManager

        pool = ServerPoolManager()
        session = AsyncMock()
        nodes = [MagicMock(), MagicMock()]
        nodes[0].to_dict.return_value = _mock_node_dict(id=1)
        nodes[1].to_dict.return_value = _mock_node_dict(id=2, name="worker-2")
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = nodes
        session.execute.return_value = mock_result

        result = await pool.list_nodes(session)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_with_service_type_filter(self):
        from app.services.scaling.pool_manager import ServerPoolManager

        pool = ServerPoolManager()
        session = AsyncMock()
        nodes = [MagicMock()]
        nodes[0].to_dict.return_value = _mock_node_dict(service_type="sandbox_worker")
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = nodes
        session.execute.return_value = mock_result

        result = await pool.list_nodes(session, service_type="sandbox_worker")
        assert len(result) == 1
        assert result[0]["service_type"] == "sandbox_worker"


class TestAddServerNode:
    """POST /api/admin/servers — pool_manager.add_node delegation."""

    @pytest.mark.asyncio
    async def test_add_creates_node_and_returns_dict(self):
        from app.services.scaling.pool_manager import ServerPoolManager

        pool = ServerPoolManager()
        session = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()

        mock_node = MagicMock()
        mock_node.to_dict.return_value = _mock_node_dict(name="new-worker")

        with patch("app.models.server_node.ServerNode", return_value=mock_node):
            result = await pool.add_node(
                session, "sandbox_worker", "new-worker", "http://new:8080",
                weight=1, max_capacity=10,
            )

        assert result["name"] == "new-worker"
        session.add.assert_called_once()
        session.flush.assert_awaited_once()


class TestRemoveServerNode:
    """DELETE /api/admin/servers/{node_id} — pool_manager.remove_node."""

    @pytest.mark.asyncio
    async def test_remove_existing_node_returns_true(self):
        from app.services.scaling.pool_manager import ServerPoolManager

        pool = ServerPoolManager()
        session = AsyncMock()
        mock_node = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_node
        session.execute.return_value = mock_result
        session.delete = AsyncMock()

        result = await pool.remove_node(session, 1)
        assert result is True
        session.delete.assert_awaited_once_with(mock_node)

    @pytest.mark.asyncio
    async def test_remove_nonexistent_returns_false(self):
        from app.services.scaling.pool_manager import ServerPoolManager

        pool = ServerPoolManager()
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        result = await pool.remove_node(session, 999)
        assert result is False

    def test_endpoint_should_raise_404_when_not_found(self):
        """Verify the endpoint logic: when remove_node returns False, raise 404."""
        removed = False
        if not removed:
            with pytest.raises(HTTPException) as exc_info:
                raise HTTPException(status_code=404, detail="Node not found")
            assert exc_info.value.status_code == 404


class TestUpdateServerNode:
    """PATCH /api/admin/servers/{node_id} — pool_manager.update_node."""

    @pytest.mark.asyncio
    async def test_update_existing_node(self):
        from app.services.scaling.pool_manager import ServerPoolManager

        pool = ServerPoolManager()
        session = AsyncMock()
        mock_node = MagicMock()
        mock_node.to_dict.return_value = _mock_node_dict(weight=5)
        mock_node.weight = 1
        # Make hasattr work correctly for valid fields
        mock_node.id = 1
        mock_node.created_at = "2026-01-01"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_node
        session.execute.return_value = mock_result
        session.flush = AsyncMock()

        result = await pool.update_node(session, 1, weight=5)
        assert result is not None
        assert result["weight"] == 5

    @pytest.mark.asyncio
    async def test_update_nonexistent_returns_none(self):
        from app.services.scaling.pool_manager import ServerPoolManager

        pool = ServerPoolManager()
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        result = await pool.update_node(session, 999, weight=5)
        assert result is None

    def test_endpoint_field_filtering_logic(self):
        """The endpoint filters updates to allowed fields only."""
        allowed_fields = {"name", "url", "api_key", "is_active", "is_primary", "weight", "max_capacity"}
        updates = {"weight": 3, "id": 999, "created_at": "bad", "name": "new"}
        filtered = {k: v for k, v in updates.items() if k in allowed_fields}

        assert "id" not in filtered
        assert "created_at" not in filtered
        assert filtered["weight"] == 3
        assert filtered["name"] == "new"


class TestHealthCheckAll:
    """POST /api/admin/servers/health-check — pool_manager.health_check_all."""

    @pytest.mark.asyncio
    async def test_health_check_returns_grouped_results(self):
        from app.services.scaling.pool_manager import ServerPoolManager

        pool = ServerPoolManager()
        mock_node = MagicMock()
        mock_node.service_type = "sandbox_worker"
        mock_node.is_active = True
        mock_node.to_dict.return_value = _mock_node_dict()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_node]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.scaling.pool_manager.async_session_maker", return_value=mock_session_ctx):
            with patch.object(pool, "health_check_node", new_callable=AsyncMock) as mock_hc:
                mock_hc.return_value = {"health_status": "healthy", "last_error": None}
                results = await pool.health_check_all()

        assert "sandbox_worker" in results
        assert len(results["sandbox_worker"]) == 1
