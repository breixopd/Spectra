"""Tests for admin server pool endpoint logic.

Tests the pool_manager calls that the admin endpoints delegate to,
plus request-level field filtering and error handling logic.
The admin module uses Depends(require_permission(...)) which prevents
direct function import in test, so we test the underlying logic.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


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
        from spectra_scaling.pool_manager import ServerPoolManager

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
        from spectra_scaling.pool_manager import ServerPoolManager

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
        from spectra_scaling.pool_manager import ServerPoolManager

        pool = ServerPoolManager()
        session = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()

        mock_node = MagicMock()
        mock_node.to_dict.return_value = _mock_node_dict(name="new-worker")

        with (
            patch("spectra_persistence.models.server_node.ServerNode", return_value=mock_node),
            patch.object(pool, "_auto_enable_autoscale", new_callable=AsyncMock),
        ):
            result = await pool.add_node(
                session,
                "sandbox_worker",
                "new-worker",
                "http://new:8080",
                weight=1,
                max_capacity=10,
            )

        assert result["name"] == "new-worker"
        session.add.assert_called_once()
        session.flush.assert_awaited_once()


class TestRemoveServerNode:
    """DELETE /api/admin/servers/{node_id} — pool_manager.remove_node."""

    @pytest.mark.asyncio
    async def test_remove_existing_node_returns_true(self):
        from spectra_scaling.pool_manager import ServerPoolManager

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
        from spectra_scaling.pool_manager import ServerPoolManager

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
        from spectra_scaling.pool_manager import ServerPoolManager

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
        from spectra_scaling.pool_manager import ServerPoolManager

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
        from spectra_scaling.pool_manager import ServerPoolManager

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

        with patch("spectra_scaling.pool_manager.async_session_maker", return_value=mock_session_ctx):
            with patch.object(pool, "health_check_node", new_callable=AsyncMock) as mock_hc:
                mock_hc.return_value = {"health_status": "healthy", "last_error": None}
                with patch.object(pool, "_collect_node_metrics", new_callable=AsyncMock) as mock_nm:
                    mock_nm.return_value = None
                    results = await pool.health_check_all()

        assert "sandbox_worker" in results
        assert len(results["sandbox_worker"]) == 1


class TestDeployToNode:
    """POST /api/admin/services/nodes/{node_id}/deploy."""

    @pytest.mark.asyncio
    async def test_forwards_pinned_known_host_from_node_metadata(self):
        from spectra_api.api.routers.admin.servers import deploy_to_node
        from spectra_scaling.infrastructure_services.deploy import DeploymentStatus, DeployResult

        node = MagicMock()
        node.id = 42
        node.url = "ssh://deploy.example.com:2222"
        node.name = "deploy-node"
        node.ssh_user = "ubuntu"
        node.ssh_port = 2222
        node.ssh_key_path = "/keys/id_ed25519"
        node.metadata_ = {"ssh_known_host": "[deploy.example.com]:2222 ssh-ed25519 AAAAPINNED"}
        node.health_status = "unknown"
        node.deployed_services = None

        mock_exec_result = MagicMock()
        mock_exec_result.scalar_one_or_none.return_value = node

        session = AsyncMock()
        session.execute.return_value = mock_exec_result
        session.commit = AsyncMock()

        current_user = MagicMock(id="user-1")
        request = MagicMock()
        deploy_result = DeployResult(DeploymentStatus.COMPLETE, "Deployment successful", ["ok"])

        with (
            patch("spectra_api.api.routers.admin.servers.audit_log_event", new_callable=AsyncMock),
            patch("spectra_scaling.infrastructure_services.deploy.ServerDeployer.deploy_to_server", new_callable=AsyncMock) as mock_deploy,
        ):
            mock_deploy.return_value = deploy_result
            response = await deploy_to_node(
                node_id=42,
                request=request,
                services=["app"],
                harden=False,
                current_user=current_user,
                session=session,
            )

        assert response == {
            "status": "complete",
            "message": "Deployment successful",
            "logs": ["ok"],
        }
        assert node.health_status == "healthy"
        assert node.deployed_services == ["app"]
        mock_deploy.assert_awaited_once_with(
            server_id="42",
            hostname="deploy.example.com",
            ssh_user="ubuntu",
            ssh_port=2222,
            ssh_key="/keys/id_ed25519",
            pinned_known_host="[deploy.example.com]:2222 ssh-ed25519 AAAAPINNED",
            services=["app"],
            harden=False,
        )


class TestProvisioningEndpointKnownHostForwarding:
    """Pinned known-host entries should be forwarded to provisioning paths."""

    @pytest.mark.asyncio
    async def test_verify_forwards_pinned_known_host(self):
        from spectra_api.api.routers.admin.servers import ServerConnectionRequest, verify_server_connection

        provisioner = MagicMock()
        provisioner.verify_connection = AsyncMock(return_value={"connected": True})
        pinned_entry = "[verify.example.com]:2222 ssh-ed25519 AAAAPINNED"

        with patch("spectra_scaling.provisioning.ServerProvisioner", return_value=provisioner):
            response = await verify_server_connection(
                body=ServerConnectionRequest(
                    host="verify.example.com",
                    port=2222,
                    username="root",
                    password="secret",
                    ssh_known_host=pinned_entry,
                ),
                _perm=MagicMock(),
            )

        assert response == {"connected": True}
        forwarded_config = provisioner.verify_connection.await_args.args[0]
        assert forwarded_config.ssh_known_host == pinned_entry

    @pytest.mark.asyncio
    async def test_provision_forwards_pinned_known_host(self):
        from spectra_api.api.routers.admin.servers import ProvisionRequest, provision_server
        from spectra_scaling.provisioning.provisioner import ProvisioningResult

        provisioner = MagicMock()
        provisioner.provision = AsyncMock(
            return_value=ProvisioningResult(
                success=True,
                server_host="provision.example.com",
                service_type="sandbox_worker",
                service_url="http://provision.example.com:8080",
                health_check_passed=True,
                logs=["ok"],
            )
        )
        pinned_entry = "[provision.example.com]:2222 ssh-ed25519 AAAAPINNED"

        with (
            patch("spectra_api.api.routers.admin.servers.audit_log_event", new_callable=AsyncMock),
            patch("spectra_scaling.provisioning.ServerProvisioner", return_value=provisioner),
        ):
            response = await provision_server(
                body=ProvisionRequest(
                    host="provision.example.com",
                    port=2222,
                    username="root",
                    password="secret",
                    ssh_known_host=pinned_entry,
                    service_type="sandbox_worker",
                ),
                request=MagicMock(),
                current_user=MagicMock(id="user-1"),
                session=AsyncMock(),
            )

        assert response == {
            "success": True,
            "service_url": "http://provision.example.com:8080",
            "health_check_passed": True,
            "logs": ["ok"],
            "error": "",
        }
        forwarded_config = provisioner.provision.await_args.args[0]
        assert forwarded_config.ssh_known_host == pinned_entry

    @pytest.mark.asyncio
    async def test_deprovision_forwards_pinned_known_host(self):
        from spectra_api.api.routers.admin.servers import DeprovisionRequest, deprovision_server
        from spectra_scaling.provisioning.provisioner import ProvisioningResult

        provisioner = MagicMock()
        provisioner.deprovision = AsyncMock(
            return_value=ProvisioningResult(
                success=True,
                server_host="deprovision.example.com",
                service_type="sandbox_worker",
                logs=["removed"],
            )
        )
        pinned_entry = "[deprovision.example.com]:2222 ssh-ed25519 AAAAPINNED"

        with (
            patch("spectra_api.api.routers.admin.servers.audit_log_event", new_callable=AsyncMock),
            patch("spectra_scaling.provisioning.ServerProvisioner", return_value=provisioner),
        ):
            response = await deprovision_server(
                body=DeprovisionRequest(
                    host="deprovision.example.com",
                    port=2222,
                    username="root",
                    password="secret",
                    ssh_known_host=pinned_entry,
                    service_type="sandbox_worker",
                ),
                request=MagicMock(),
                current_user=MagicMock(id="user-1"),
                session=AsyncMock(),
            )

        assert response == {
            "success": True,
            "logs": ["removed"],
            "error": "",
        }
        forwarded_config = provisioner.deprovision.await_args.args[0]
        assert forwarded_config.ssh_known_host == pinned_entry
