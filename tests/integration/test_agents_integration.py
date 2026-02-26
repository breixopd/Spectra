import pytest
import pytest_asyncio
from unittest.mock import MagicMock, patch
from app.services.ai.agents.tool_selector import (
    ToolSelectorAgent,
    ToolSelectorInput,
    ToolSelectorOutput,
)
from app.services.ai.agents.scope import ScopeAgent, ScopeInput, ScopeAction
from app.services.ai.agents.base import ToolAction, AgentContext
from app.core.config import settings

# Force Mock Provider
settings.AI_PROVIDER = "mock"


@pytest.fixture
def mock_llm():
    from app.services.ai.llm import get_llm_client

    # Reset singleton if needed or just get new one
    client = get_llm_client(provider="mock")
    client.reset()
    return client


@pytest.fixture
def mock_registry():
    with patch("app.services.ai.agents.tool_selector.get_registry") as mock_get:
        registry = MagicMock()
        mock_tool = MagicMock()
        mock_tool.config.id = "nmap"
        mock_tool.config.metadata.capabilities = ["port_scan"]
        mock_tool.config.metadata.prerequisites = []
        mock_tool.config.metadata.risk_level = "low"
        mock_tool.config.get_ai_summary.return_value = "Nmap port scanner"

        registry.get_available_tools.return_value = [mock_tool]
        registry.get_tool.return_value = mock_tool
        mock_get.return_value = registry
        yield registry


@pytest.mark.asyncio
async def test_tool_selector_flow(mock_llm, mock_registry):
    """Test ToolSelector using Mock LLM."""
    # Setup structured response for the agent
    mock_llm.structured_responses = {
        "ToolSelectorOutput": {
            "action_type": "run_tool",
            "tool_name": "nmap",
            "tool_args": {"-p": "80"},
            "reasoning": "Mock reasoning",
            "confidence": 0.9,
            "alternatives": [],
            "target": "1.1.1.1",
            "estimated_duration": 60,
            "risk_level": "low",
        }
    }

    agent = ToolSelectorAgent(mock_llm)

    # Input
    inp = ToolSelectorInput(target="1.1.1.1", current_phase="discovery")
    context = MagicMock(spec=AgentContext)
    context.stealth_mode = False
    context.session_id = "test-session"

    # Execute
    result = await agent.execute(context, inp)

    # Verify
    assert result.success is True
    assert isinstance(result.action, ToolAction)
    assert result.action.tool_name == "nmap"


@pytest.mark.asyncio
async def test_scope_agent_flow(mock_llm):
    """Test ScopeAgent using Mock LLM."""
    mock_llm.structured_responses = {
        "ScopeAction": {
            "action_type": "define_scope",
            "confidence": 0.9,
            "risk_level": "low",
            "reasoning": "Parsed targets",
            "targets": [
                {
                    "value": "1.1.1.1",
                    "target_type": "ip",
                    "resolved_ips": [],
                    "ports": [],
                    "notes": "",
                }
            ],
            "exclusions": [],
            "total_hosts": 1,
            "warnings": [],
        }
    }

    agent = ScopeAgent(mock_llm)
    inp = ScopeInput(raw_input="Include 1.1.1.1 but check for others")
    context = MagicMock(spec=AgentContext)
    context.session_id = "test-session"

    result = await agent.execute(context, inp)

    assert result.success is True
    assert result.action.total_hosts >= 1
    assert result.action.targets[0].value == "1.1.1.1"


@pytest.mark.asyncio
async def test_exploit_crafter_flow(mock_llm):
    """Test ExploitCrafter using Mock LLM."""
    from app.services.ai.agents.exploit_crafter import (
        ExploitCrafter,
        ExploitInput,
        ExploitAction,
    )

    mock_llm.structured_responses = {
        "ExploitAction": {
            "action_type": "execute_exploit",
            "exploit_name": "test_exploit",
            "payload_type": "reverse_tcp",
            "configuration": {"LHOST": "127.0.0.1"},
            "attempt_number": 1,
            "confidence": 0.8,
            "risk_level": "high",
            "reasoning": "Valid exploit found",
        }
    }

    agent = ExploitCrafter(mock_llm)
    inp = ExploitInput(
        target="1.1.1.1", vulnerability_id="CVE-2024-0001", service_info={"port": 80}
    )
    context = MagicMock(spec=AgentContext)
    context.session_id = "test-session"
    context.previous_actions = []

    # Mock specialized methods via patching if needed or rely on MockLLM for simple flow
    # _find_exploit_candidates calls RAG which might fail if not mocked
    with patch(
        "app.services.ai.agents.exploit_crafter.ExploitCrafter._find_exploit_candidates"
    ) as mock_find:
        mock_find.return_value = [{"name": "test_exploit", "type": "cve"}]

        result = await agent.execute(context, inp)

        assert result.success is True
        assert isinstance(result.action, ExploitAction)
        assert result.action.exploit_name == "test_exploit"


@pytest.mark.asyncio
async def test_mission_controller_planning(mock_llm):
    """Test MissionController planning logic."""
    from app.services.ai.agents.mission_controller import (
        MissionController,
        MissionInput,
        MissionPlan,
        MissionType,
    )
    from app.core.enums import AssessmentPhase

    mock_llm.structured_responses = {
        "MissionPlan": {
            "action_type": "mission_plan",
            "mission_type": "full_assessment",
            "tasks": [
                {
                    "task_id": "t1",
                    "description": "Scan",
                    "agent_type": "tool_selector",
                    "phase": "discovery",
                    "priority": 1,
                }
            ],
            "current_phase": "scope",
            "confidence": 0.9,
            "risk_level": "low",
            "reasoning": "Standard plan",
        }
    }

    # Mock dependency imports inside execute method
    with (
        patch(
            "app.services.ai.knowledge.get_available_tools_context",
            new_callable=MagicMock,
        ) as mock_tools,
        patch(
            "app.services.ai.knowledge.get_mission_context", new_callable=MagicMock
        ) as mock_ctx,
        patch(
            "app.services.ai.knowledge.get_full_methodology", new_callable=MagicMock
        ) as mock_meth,
    ):
        mock_tools.return_value = "Tools available"
        mock_ctx.return_value = "Context"
        mock_meth.return_value = "Methodology"

        agent = MissionController(mock_llm)
        inp = MissionInput(directive="Hack everything")
        context = MagicMock(spec=AgentContext)
        context.session_id = "test-session"
        context.target = "1.1.1.1"

        result = await agent.execute(context, inp)

        assert result.success is True
        assert isinstance(result.action, MissionPlan)
        assert result.action.mission_type == MissionType.FULL_ASSESSMENT
