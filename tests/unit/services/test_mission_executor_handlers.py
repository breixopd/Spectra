from unittest.mock import AsyncMock, MagicMock

import pytest

from app.mission.core.enums import AssessmentPhase
from app.services.ai.agents.base import (
    AgentContext,
    AgentResult,
    ToolAction,
)
from app.services.ai.agents.mission_controller import Task
from app.services.mission.executor.handlers import TaskDispatcher
from app.services.mission.mission import Mission


@pytest.fixture
def mock_dependencies():
    tool_service = AsyncMock()
    exploitation_manager = AsyncMock()
    consensus = AsyncMock()

    agents = {
        "tool_selector": AsyncMock(),
        "exploit_crafter": AsyncMock(),
        "exploit_verifier": AsyncMock(),
        "scope_agent": AsyncMock(),
        "reporter": AsyncMock(),
        "vector_generator": AsyncMock(),
    }

    return tool_service, exploitation_manager, consensus, agents


@pytest.fixture
def dispatcher(mock_dependencies):
    return TaskDispatcher(*mock_dependencies)


@pytest.fixture
def mock_mission():
    mission = MagicMock(spec=Mission)
    mission.target = "192.168.1.1"
    mission.get_known_services.return_value = []
    mission.get_known_vulns.return_value = []
    mission.tools_run = set()
    # Mock attack surface
    mission.attack_surface = MagicMock()
    mission.attack_surface.vulnerabilities = []
    mission.attack_surface.vectors = []
    # Mock findings
    mission.findings = []
    # Mock plan
    mission.plan = MagicMock()
    mission.plan.tasks = []
    # Mock blackboard and task tree
    mission.blackboard = MagicMock()
    mission.blackboard.get_context_for_agent.return_value = ""
    mission.task_tree = MagicMock()
    return mission


@pytest.fixture
def mock_context():
    return AgentContext(mission_id="test-mission-1", session_id="test-session", request_id="req-1")


@pytest.mark.asyncio
async def test_dispatch_delegates_correctly(dispatcher, mock_mission, mock_context):
    """Test that dispatch calls the correct handler."""
    task = Task(
        task_id="t1",
        description="test",
        agent_type="tool_selector",
        phase=AssessmentPhase.DISCOVERY,
    )

    # We can spy on the handler or mock the agent execution
    # Since _get_task_handler returns a bound method, we can mock the agent execution to verify flow

    agent = dispatcher.agents["tool_selector"]
    action = ToolAction(
        tool_name="nmap",
        args={},
        target="192.168.1.1",
        confidence=0.9,
        reasoning="Test reasoning",
    )
    agent.execute.return_value = AgentResult(success=True, action=action)

    await dispatcher.dispatch(mock_mission, task, mock_context)

    agent.execute.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_unknown_agent_fallback(dispatcher, mock_mission, mock_context):
    """Test fallback logic for unknown agents mapping to tool_selector."""
    task = Task(
        task_id="t1",
        description="test",
        agent_type="discovery",
        phase=AssessmentPhase.DISCOVERY,
    )

    agent = dispatcher.agents["tool_selector"]
    action = ToolAction(
        tool_name="nmap",
        args={},
        target="192.168.1.1",
        confidence=0.9,
        reasoning="Test reasoning",
    )
    agent.execute.return_value = AgentResult(success=True, action=action)

    await dispatcher.dispatch(mock_mission, task, mock_context)

    agent.execute.assert_called_once()  # Should use tool_selector


@pytest.mark.asyncio
async def test_handle_tool_selector_success(dispatcher, mock_mission, mock_context):
    """Test successful tool selection and execution."""
    task = Task(
        task_id="t1",
        description="Scan it",
        agent_type="tool_selector",
        phase=AssessmentPhase.DISCOVERY,
        parameters={"tool_hint": "nmap"},
    )

    agent = dispatcher.agents["tool_selector"]
    action = ToolAction(
        tool_name="nmap",
        args={"-p": "80"},
        target="192.168.1.1",
        confidence=0.9,
        reasoning="Test reasoning",
    )
    agent.execute.return_value = AgentResult(success=True, action=action)

    dispatcher.tool_service.execute_tool_action.return_value = True

    await dispatcher._handle_tool_selector(mock_mission, task, mock_context)

    agent.execute.assert_called_once()
    dispatcher.tool_service.execute_tool_action.assert_called_once_with(mock_mission, action, mock_context)


@pytest.mark.asyncio
async def test_handle_tool_selector_no_tool(dispatcher, mock_mission, mock_context):
    """Test tool selector returning no tool (skip)."""
    task = Task(
        task_id="t1",
        description="Scan",
        agent_type="tool_selector",
        phase=AssessmentPhase.DISCOVERY,
    )

    agent = dispatcher.agents["tool_selector"]
    # Mock action to allow arbitrary attributes like skip_reason
    action = MagicMock()
    action.tool_name = ""
    action.skip_reason = "No useful tools"

    agent.execute.return_value = AgentResult(success=True, action=action)

    await dispatcher._handle_tool_selector(mock_mission, task, mock_context)

    agent.execute.assert_called_once()
    dispatcher.tool_service.execute_tool_action.assert_not_called()
    mock_mission.log.assert_called()


@pytest.mark.asyncio
async def test_update_attack_surface_service(dispatcher, mock_mission):
    """Test updating attack surface with a service finding."""
    finding = {
        "host": "1.2.3.4",
        "port": 80,
        "service": "http",
        "product": "nginx",
        "version": "1.0",
    }

    await dispatcher._update_attack_surface(mock_mission, finding)

    mock_mission.add_service.assert_called_once_with(
        host="1.2.3.4", port=80, service="http", product="nginx", version="1.0"
    )


@pytest.mark.asyncio
async def test_update_attack_surface_vuln(dispatcher, mock_mission):
    """Test updating attack surface with a vulnerability finding."""
    finding = {"name": "CVE-2024-1234", "severity": "critical", "id": "vuln-1"}

    await dispatcher._update_attack_surface(mock_mission, finding)

    mock_mission.add_vulnerability.assert_called_once()


@pytest.mark.asyncio
async def test_scope_handler(dispatcher, mock_mission, mock_context):
    """Test scope handler delegates to agent."""
    task = Task(
        task_id="t1",
        description="Scope",
        agent_type="scope",
        phase=AssessmentPhase.SCOPE,
    )
    agent = dispatcher.agents["scope_agent"]
    agent.execute.return_value = AgentResult(success=True, action=MagicMock(targets=["1.1.1.1"]))

    await dispatcher._handle_scope(mock_mission, task, mock_context)

    agent.execute.assert_called_once()


@pytest.mark.asyncio
async def test_reporter_handler(dispatcher, mock_mission, mock_context):
    """Test reporter handler."""
    mock_mission.directive = "Test Mission"
    task = Task(
        task_id="t1",
        description="Report",
        agent_type="reporter",
        phase=AssessmentPhase.REPORTING,
    )
    agent = dispatcher.agents["reporter"]
    agent.execute.return_value = AgentResult(success=True)

    await dispatcher._handle_reporter(mock_mission, task, mock_context)

    agent.execute.assert_called_once()
