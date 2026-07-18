"""VPN-required mission safety regressions."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectra_mission.manager.execution import MissionExecutionManager
from spectra_mission.manager.lifecycle import MissionLifecycleManager
from spectra_mission.mission import Mission


@pytest.mark.asyncio
async def test_initialize_mission_fails_when_vpn_worker_rejects_connect():
    lifecycle = MissionLifecycleManager({})
    lifecycle.update_db_status = AsyncMock()
    mission = Mission("198.51.100.10", "validate the service", vpn_config="engagement-vpn")

    vpn_manager = MagicMock()
    vpn_manager.connect = AsyncMock(return_value={"job_id": "vpn-job-1"})
    vpn_job = MagicMock()
    vpn_job.result = AsyncMock(return_value={"success": False, "error": "interface failed"})

    with (
        patch("spectra_tools.vpn.VPNManager", return_value=vpn_manager),
        patch("spectra_infra.queue.Job", return_value=vpn_job),
    ):
        context = await lifecycle.initialize_mission(mission)

    assert context is None
    assert mission.status == "failed"
    assert any("VPN" in entry and "failed" in entry.lower() for entry in mission.logs)
    vpn_job.result.assert_awaited_once_with(timeout=30)


@pytest.mark.asyncio
async def test_sandbox_creation_refuses_missing_requested_vpn_config():
    execution = MissionExecutionManager(MagicMock(), MagicMock())
    mission = Mission("198.51.100.10", "validate the service", vpn_config="engagement-vpn")

    pool = MagicMock(available=True, is_remote=False)
    vpn_manager = MagicMock()
    vpn_manager._download_to_local = AsyncMock(return_value=None)

    with (
        patch("spectra_system.notifications.notify_mission_started", new_callable=AsyncMock, create=True),
        patch("spectra_tools.sandbox.get_sandbox_pool", return_value=pool),
        patch("spectra_tools.vpn.VPNManager", return_value=vpn_manager),
        pytest.raises(RuntimeError, match="refusing direct-network fallback"),
    ):
        await execution._create_sandbox(mission)

    pool.create.assert_not_called()
