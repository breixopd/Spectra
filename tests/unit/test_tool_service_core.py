import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from app.services.tools.service import (
    ToolExecutionService,
    ToolExecutionRequest,
    ToolExecutionResult,
)
from app.services.tools.models import (
    RegisteredTool,
    ToolStatus,
    ToolConfig,
    OutputFormat,
)
from app.services.ai.agents.safety import SafetyAction
from app.services.ai.agents.base import ActionRisk


@pytest.fixture
def mock_service_context():
    with (
        patch("app.services.tools.service.get_registry") as mock_get_registry,
        patch("app.services.tools.service.SafetySupervisorAgent") as MockSafety,
        patch("app.services.tools.service.VotingSystem") as MockVoting,
        patch("app.services.tools.service.CommandToolAdapter") as MockAdapter,
    ):
        registry = MagicMock()
        registry.sync_status_from_redis = AsyncMock()
        mock_get_registry.return_value = registry

        service = ToolExecutionService(llm_client=MagicMock())
        # Manually assign AsyncMocks to ensure await works
        service.safety_supervisor = AsyncMock()
        service.consensus = AsyncMock()

        yield {
            "service": service,
            "registry": registry,
            "safety_class": MockSafety,
            "voting_class": MockVoting,
            "adapter_class": MockAdapter,
        }


@pytest.mark.asyncio
async def test_execute_tool_success(mock_service_context):
    service = mock_service_context["service"]
    registry = mock_service_context["registry"]
    MockAdapter = mock_service_context["adapter_class"]

    mission = MagicMock()
    mission.id = "mission-1"
    mission.target = "127.0.0.1"
    mission.directive = "Scan localhost"

    # Mock tool
    tool = MagicMock()
    tool.is_available = True
    tool.config.id = "nmap"
    tool.config.execution.args_schema = None
    registry.get_tool.return_value = tool

    # Config adapter instance
    mock_adapter_instance = MockAdapter.return_value
    mock_adapter_instance.build_command.return_value = "nmap -p 80 127.0.0.1"

    result_obj = ToolExecutionResult(
        tool_id="nmap",
        target="127.0.0.1",
        success=True,
        exit_code=0,
        stdout="ok",
        stderr="",
        duration_seconds=1.0,
    )

    # Config Safety
    safety_result = MagicMock()
    safety_result.success = True
    safety_result.action = SafetyAction(
        name="safety",
        allowed=True,
        reason="Safe",
        confidence=1.0,
        risk_level=ActionRisk.LOW,
        reasoning="All good",
    )
    service.safety_supervisor.execute.return_value = safety_result

    # Mock the ARQ worker execution path
    service._execute_via_worker = AsyncMock(return_value=result_obj)

    result = await service.execute_request(
        mission=mission, tool_name="nmap", target="127.0.0.1"
    )

    if not result.success:
        print(f"FAILED stderr: {result.stderr}")

    assert result.success is True
    assert result.tool_id == "nmap"
    service._execute_via_worker.assert_called_once()
    service.safety_supervisor.execute.assert_called()


@pytest.mark.asyncio
async def test_execute_tool_not_found(mock_service_context):
    service = mock_service_context["service"]
    registry = mock_service_context["registry"]
    mission = MagicMock()
    mission.id = "m1"
    mission.target = "127.0.0.1"
    mission.directive = "Scan localhost"

    registry.get_tool.return_value = None

    result = await service.execute_request(mission, "ghost", "127.0.0.1")
    assert result.success is False
    assert "Tool not available" in result.stderr


@pytest.mark.asyncio
async def test_execute_tool_safety_block(mock_service_context):
    service = mock_service_context["service"]
    registry = mock_service_context["registry"]
    MockAdapter = mock_service_context["adapter_class"]
    mission = MagicMock()
    mission.id = "m1"
    mission.target = "127.0.0.1"
    mission.directive = "Scan localhost"

    tool = MagicMock()
    tool.is_available = True
    tool.config.id = "nmap"
    tool.config.execution.args_schema = None
    registry.get_tool.return_value = tool

    # Safety blocks
    safety_result = MagicMock()
    safety_result.success = True
    safety_result.action = SafetyAction(
        name="safety",
        allowed=False,
        reason="Unsafe",
        confidence=1.0,
        risk_level=ActionRisk.HIGH,
        reasoning="Blocked",
    )
    service.safety_supervisor.execute.return_value = safety_result

    # Adapter setup needed for build_command
    MockAdapter.return_value.build_command.return_value = "cmd"

    result = await service.execute_request(mission, "nmap", "127.0.0.1")
    assert result.success is False
    assert "Blocked by Safety Supervisor" in result.stderr


@pytest.mark.asyncio
async def test_execute_tool_consensus_block(mock_service_context):
    service = mock_service_context["service"]
    registry = mock_service_context["registry"]
    MockAdapter = mock_service_context["adapter_class"]
    mission = MagicMock()
    mission.id = "m1"
    mission.target = "127.0.0.1"
    mission.directive = "Scan localhost"

    tool = MagicMock()
    tool.is_available = True
    tool.config.id = "nmap"
    tool.config.execution.args_schema = None
    registry.get_tool.return_value = tool

    # Safety passes
    safety_result = MagicMock()
    safety_result.success = True
    safety_result.action = SafetyAction(
        name="safety",
        allowed=True,
        reason="Safe",
        confidence=1.0,
        risk_level=ActionRisk.LOW,
        reasoning="Good",
    )
    service.safety_supervisor.execute.return_value = safety_result

    MockAdapter.return_value.build_command.return_value = "cmd"

    # Consensus blocks
    vote_result = MagicMock()
    # VotingSystem.vote_on_action returns AgentResult or specialized VoteResult?
    # service.py: vote_result = await self.consensus.vote_on_action(...)
    # if vote_result.status != "approved": ...
    # So it expects an object with .status and .escalation_reason
    vote_result.status = "rejected"
    vote_result.escalation_reason = "Vetoed"
    service.consensus.vote_on_action.return_value = vote_result

    # Ensure risk level high triggers consensus
    result = await service.execute_request(
        mission, "nmap", "127.0.0.1", risk_level="high"
    )

    if "Blocked by Consensus" not in result.stderr:
        print(f"FAILED Consensus stderr: {result.stderr}")

    assert result.success is False
    assert "Blocked by Consensus" in result.stderr
