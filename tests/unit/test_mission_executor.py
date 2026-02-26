
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from app.services.mission.executor import MissionExecutor
from app.services.mission.mission import Mission
from app.services.ai.agents.mission_controller import Task, AssessmentPhase
from app.services.ai.agents.base import AgentContext, AgentResult, ToolAction

@pytest.fixture
def mock_executor_context():
    # Use source paths for patching to reliability
    with patch("app.services.tools.service.ToolExecutionService") as MockToolService, \
         patch("app.services.mission.exploitation.ExploitationManager") as MockExploitManager, \
         patch("app.services.ai.agents.tool_selector.ToolSelectorAgent") as MockToolSelector, \
         patch("app.services.ai.consensus.VotingSystem") as MockVoting:
        
        # Mocks
        mock_llm = AsyncMock()
        mock_tool_service = MockToolService.return_value
        mock_exploit_manager = MockExploitManager.return_value
        mock_tool_selector = MockToolSelector.return_value
        mock_voting = MockVoting.return_value
        
        executor = MissionExecutor(mock_llm)
        # Re-inject mocks into dispatcher where they are actually used
        executor.tool_service = mock_tool_service
        executor.exploitation_manager = mock_exploit_manager
        
        executor.dispatcher.tool_service = mock_tool_service
        executor.dispatcher.exploitation_manager = mock_exploit_manager
        executor.dispatcher.consensus = mock_voting
        
        # Inject agents into dispatcher
        executor.dispatcher.agents["tool_selector"] = mock_tool_selector
        executor.consensus = mock_voting
        
        yield {
            "executor": executor,
            "tool_service": mock_tool_service,
            "exploit_manager": mock_exploit_manager,
            "tool_selector": mock_tool_selector
        }

@pytest.mark.asyncio
async def test_execute_task_tool_selector(mock_executor_context):
    executor = mock_executor_context["executor"]
    tool_selector = mock_executor_context["tool_selector"]
    tool_service = mock_executor_context["tool_service"]
    
    mission = Mission("127.0.0.1", "test")
    # Need to mock mission.log to avoid errors if logs used
    mission.log = MagicMock()
    
    task = Task(task_id="t1", description="desc", agent_type="tool_selector", phase=AssessmentPhase.DISCOVERY)
    context = AgentContext(mission_id="test-mission-1", session_id="1", target="127.0.0.1", mission="test")
    
    # Mock Selection
    select_result = MagicMock()
    select_result.success = True
    action = ToolAction(
        tool_name="nmap",
        tool_args={"-p": "80"},
        risk_level="low",
        reasoning="test",
        estimated_duration=60,
        confidence=1.0,
        target="127.0.0.1"
    )
    select_result.action = action
    tool_selector.execute = AsyncMock(return_value=select_result)
    
    # Mock Execution
    tool_service.execute_tool_action = AsyncMock(return_value=True)
    
    await executor.execute_task(mission, task, context)
    
    tool_selector.execute.assert_called_once()
    tool_service.execute_tool_action.assert_called_once()

@pytest.mark.asyncio
async def test_execute_task_tool_selector_no_tool(mock_executor_context):
    executor = mock_executor_context["executor"]
    tool_selector = mock_executor_context["tool_selector"]
    tool_service = mock_executor_context["tool_service"]
    
    mission = Mission("127.0.0.1", "test")
    mission.log = MagicMock()
    task = Task(task_id="t1", description="desc", agent_type="tool_selector", phase=AssessmentPhase.DISCOVERY)
    context = AgentContext(mission_id="test-mission-1", session_id="1", target="127.0.0.1", mission="test")
    
    # Mock Selection - No tool selected (e.g. phase complete)
    select_result = MagicMock()
    select_result.success = True
    action = ToolAction(
        tool_name="",
        tool_args={},
        risk_level="low",
        reasoning="none",
        confidence=1.0,
        target="127.0.0.1"
    )
    select_result.action = action
    tool_selector.execute = AsyncMock(return_value=select_result)
    
    await executor.execute_task(mission, task, context)
    
    tool_selector.execute.assert_called_once()
    tool_service.execute_tool_action.assert_not_called()

@pytest.mark.asyncio
async def test_handle_exploit_crafter(mock_executor_context):
    executor = mock_executor_context["executor"]
    exploit_manager = mock_executor_context["exploit_manager"]
    
    mission = Mission("127.0.0.1", "test")
    mission.log = MagicMock()
    task = Task(task_id="t1", description="exploit", agent_type="exploit_crafter", phase=AssessmentPhase.EXPLOITATION)
    context = AgentContext(mission_id="test-mission-1", session_id="1", target="127.0.0.1", mission="test")
    
    exploit_manager.run_iterative_exploitation = AsyncMock()
    
    await executor.execute_task(mission, task, context)
    
    exploit_manager.run_iterative_exploitation.assert_called_once()

@pytest.mark.asyncio
async def test_unknown_agent_type(mock_executor_context):
    executor = mock_executor_context["executor"]
    
    mission = Mission("127.0.0.1", "test")
    mission.log = MagicMock()
    # Try a type that doesn't map to anything and doesn't match fallback
    # _get_task_handler checks dict, then suffix "_agent", then phase keywords.
    # "unknown_xyz" -> no.
    task_random = Task(task_id="t2", description="random", agent_type="unknown_xyz", phase=AssessmentPhase.DISCOVERY)
    context = AgentContext(mission_id="test-mission-1", session_id="1", target="127.0.0.1", mission="test")
    
    await executor.execute_task(mission, task_random, context)
    # Should log "Unknown agent type"
    mission.log.assert_called()
