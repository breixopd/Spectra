from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spectra_tools.service import ToolExecutionResult, ToolExecutionService


@pytest.fixture
def service_and_mission():
    service = ToolExecutionService(llm_client=MagicMock())
    mission = MagicMock()
    mission.id = "mission-1"
    mission.target = "127.0.0.1"
    mission.directive = "Scan localhost"
    return service, mission


@pytest.mark.asyncio
async def test_execute_tool_success(service_and_mission):
    service, mission = service_and_mission
    tool = MagicMock()
    result_obj = ToolExecutionResult(
        tool_id="nmap",
        target="127.0.0.1",
        success=True,
        exit_code=0,
        stdout="ok",
        stderr="",
        duration_seconds=1.0,
    )

    service._validate_and_resolve_tool = AsyncMock(return_value=(tool, None))
    service._apply_safety_and_consensus = AsyncMock(return_value=("nmap -p 80 127.0.0.1", None))
    service._dispatch_and_process_result = AsyncMock(return_value=result_obj)

    with (
        patch(
            "spectra_tools.service.build_execution_request",
            return_value=(MagicMock(), MagicMock(), "nmap -p 80 127.0.0.1", "/tmp/out"),
        ),
        patch("spectra_tools.service.record_to_memory"),
    ):
        result = await service.execute_request(mission=mission, tool_name="nmap", target="127.0.0.1")

    assert result.success is True
    assert result.tool_id == "nmap"
    service._apply_safety_and_consensus.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_tool_not_found(service_and_mission):
    service, mission = service_and_mission
    service._validate_and_resolve_tool = AsyncMock(return_value=(None, None))

    result = await service.execute_request(mission, "ghost", "127.0.0.1")
    assert result.success is False
    assert "Tool not found" in result.stderr


@pytest.mark.asyncio
async def test_execute_tool_safety_block(service_and_mission):
    service, mission = service_and_mission
    tool = MagicMock()
    blocked = ToolExecutionResult(
        tool_id="nmap",
        target="127.0.0.1",
        success=False,
        exit_code=-1,
        stdout="",
        stderr="Blocked by Safety Supervisor: Unsafe",
        duration_seconds=0.0,
    )

    service._validate_and_resolve_tool = AsyncMock(return_value=(tool, None))
    service._apply_safety_and_consensus = AsyncMock(return_value=("cmd", blocked))

    with patch(
        "spectra_tools.service.build_execution_request", return_value=(MagicMock(), MagicMock(), "cmd", "/tmp/out")
    ):
        result = await service.execute_request(mission, "nmap", "127.0.0.1")
    assert result.success is False
    assert "Blocked by Safety Supervisor" in result.stderr


@pytest.mark.asyncio
async def test_execute_tool_consensus_block(service_and_mission):
    service, mission = service_and_mission
    tool = MagicMock()
    blocked = ToolExecutionResult(
        tool_id="nmap",
        target="127.0.0.1",
        success=False,
        exit_code=-1,
        stdout="",
        stderr="Blocked by Consensus",
        duration_seconds=0.0,
    )

    service._validate_and_resolve_tool = AsyncMock(return_value=(tool, None))
    service._apply_safety_and_consensus = AsyncMock(return_value=("cmd", blocked))

    with patch(
        "spectra_tools.service.build_execution_request", return_value=(MagicMock(), MagicMock(), "cmd", "/tmp/out")
    ):
        result = await service.execute_request(mission, "nmap", "127.0.0.1", risk_level="high")
    assert result.success is False
    assert "Blocked by Consensus" in result.stderr
