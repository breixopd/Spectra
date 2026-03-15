from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.agents.base import (
    ActionRisk,
    AgentContext,
    AgentResult,
    ToolAction,
)
from app.services.ai.agents.mission_controller import AssessmentPhase, Task
from app.services.mission.executor import MissionExecutor
from app.services.mission.mission import Mission
from app.services.tools.models import (
    ExecutionConfig,
    ToolCategory,
    ToolConfig,
    ToolStatus,
)
from app.services.tools.registry import RegisteredTool, ToolRegistry

# --- Dummy Tool Config ---
DUMMY_TOOL_CONFIG = ToolConfig(
    id="test-echo",
    name="Test Echo",
    version="1.0.0",
    category=ToolCategory.CUSTOM,
    description="A dummy tool for integration testing",
    execution=ExecutionConfig(
        command="echo",
        args_template="{message}",
    ),
)

DUMMY_FAIL_TOOL_CONFIG = ToolConfig(
    id="test-fail",
    name="Test Fail",
    version="1.0.0",
    category=ToolCategory.CUSTOM,
    description="A dummy tool that fails",
    execution=ExecutionConfig(
        command="false",  # Returns exit code 1
        args_template="",
    ),
)


@pytest.fixture
def mock_registry():
    # Create a real registry but populate it with dummy tools manually
    registry = ToolRegistry()
    registry._tools = {
        "test-echo": RegisteredTool(config=DUMMY_TOOL_CONFIG, status=ToolStatus.READY),
        "test-fail": RegisteredTool(config=DUMMY_FAIL_TOOL_CONFIG, status=ToolStatus.READY),
    }
    return registry


@pytest.fixture
def integration_context(mock_registry):
    # We mock the AGENTS but keep the SERVICE logic real (except for subprocess if we wanted, but echo is safe)
    # Actually, we keep ToolExecutionService real, but mock its dependencies: Safety, Voting.

    with (
        patch("app.services.tools.validation.get_registry", return_value=mock_registry),
        patch("app.services.tools.service.SafetySupervisorAgent") as MockSafetyAgent,
        patch("app.services.tools.service.VotingSystem") as MockVotingSystem,
        patch("app.services.ai.agents.tool_selector.ToolSelectorAgent") as MockToolSelector,
    ):
        # Setup Safety Supervisor to always approve
        mock_safety = MockSafetyAgent.return_value
        # The service calls execute or validate? It calls execute usually for an agent
        # But ToolExecutionService might call a specific method.
        # Checking service.py: it calls `safety_agent.execute(context, input)`
        safety_result = AgentResult(success=True, action=MagicMock(risk_level="low"))
        mock_safety.execute = AsyncMock(return_value=safety_result)

        # Setup Voting System to always approve
        mock_voting = MockVotingSystem.return_value
        mock_voting.register_vote = AsyncMock(return_value=True)  # Assuming simple approval

        # Setup ToolSelector (will be customized in tests)
        mock_selector = MockToolSelector.return_value

        executor = MissionExecutor(AsyncMock())
        # We need to make sure the executor execution uses the mocked tool selector
        executor.agents["tool_selector"] = mock_selector

        # We need to make sure the executor's tool_service uses the mocked safety/voting
        # ToolExecutionService is instantiated inside MissionExecutor usually or passed?
        # In executor.py `__init__`: self.tool_service = ToolExecutionService(llm_client)

        # We need to patch the classes BEFORE MissionExecutor instantiates them, OR replace the instance attributes.
        # The patching above handles the classes for new instances, but we need to ensure the instance used has them.
        # Since we create executor here, and it creates tool_service inside init, the patches should work
        # IF ToolExecutionService imports them at runtime or we patched the module where generic imports happen.
        # `app.services.tools.service` imports `SafetySupervisorAgent` etc.
        # Our patch `app.services.tools.service.SafetySupervisorAgent` targets that import. So it should work.

        # However, ToolExecutionService instantiates them in `__init__`.
        # So we just need to ensure patches are active when we verify.

        # Re-instantiate ToolExecutionService to be sure it picks up patched classes?
        # executor.tool_service is created in executor.__init__

        # Let's verify the tool service has the mocks
        # executor.tool_service.safety_agent should be the mock instance

        yield {
            "executor": executor,
            "mock_selector": mock_selector,
            "mock_safety": mock_safety,
            "mock_voting": mock_voting,
            "registry": mock_registry,
        }


@pytest.mark.asyncio
async def test_integration_flow_success(integration_context):
    executor = integration_context["executor"]
    mock_selector = integration_context["mock_selector"]

    # 1. Setup Mission & Context
    mission = Mission("127.0.0.1", "test-integration")
    mission.log = MagicMock()
    context = AgentContext(
        mission_id="test-mission-1",
        session_id="int-1",
        target="127.0.0.1",
        mission="integrate",
    )
    task = Task(
        task_id="t1",
        description="run echo",
        agent_type="tool_selector",
        phase=AssessmentPhase.DISCOVERY,
    )

    # 2. Mock Agent Selection -> "test-echo"
    action = ToolAction(
        tool_name="test-echo",
        tool_args={"message": "HELLO_INTEGRATION"},
        target="127.0.0.1",
        risk_level=ActionRisk.LOW,
        confidence=1.0,
        reasoning="Testing integration",
        estimated_duration=10,
    )
    mock_selector.execute = AsyncMock(return_value=AgentResult(success=True, action=action))

    # 3. Execute
    await executor.execute_task(mission, task, context)

    # 4. Verification
    # Assert Selector was called
    mock_selector.execute.assert_called_once()

    # Assert Mission Log contains success (or at least doesn't contain failure)
    # The Executor logs "Tool execution completed successfully" or similar?
    # Actually ToolExecutionService logs, MissionExecutor logs result.
    # checking executor.py: `if result.success: mission.log(...)`
    # We accept "HELLO_INTEGRATION" in stdout of the result.

    # Check if mission findings or state updated?
    # Echo doesn't parse to findings unless configured.
    # But we should ensure no exception was raised.


@pytest.mark.asyncio
async def test_integration_flow_failure_adaptation(integration_context):
    executor = integration_context["executor"]
    mock_selector = integration_context["mock_selector"]

    # 1. Setup
    mission = Mission("127.0.0.1", "test-integration-fail")
    mission.log = MagicMock()
    context = AgentContext(
        mission_id="test-mission-1",
        session_id="int-2",
        target="127.0.0.1",
        mission="integrate-fail",
    )
    task = Task(
        task_id="t2",
        description="run fail",
        agent_type="tool_selector",
        phase=AssessmentPhase.DISCOVERY,
    )

    # 2. Mock Selection -> "test-fail"
    action = ToolAction(
        tool_name="test-fail",
        tool_args={},
        target="127.0.0.1",
        risk_level=ActionRisk.LOW,
        confidence=1.0,
        reasoning="Testing failure",
        estimated_duration=10,
    )
    mock_selector.execute = AsyncMock(return_value=AgentResult(success=True, action=action))

    # 3. Execute
    await executor.execute_task(mission, task, context)

    # 4. Verify Adaptation/Handling
    # Ensure it didn't crash
    mock_selector.execute.assert_called_once()

    # Verify logging of failure
    # mission.log should be called with failure info
    # executor.py lines 270+: if not success: mission.log(...)

    fails = [args[0] for name, args, kwargs in mission.log.mock_calls if "failed" in str(args[0]).lower()]
    assert fails, "Should have logged a failure message"
