"""
Unit tests for AI services: LLM clients, Agents, and Consensus.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from spectra_ai.llm import (
    LLMResponse,
    get_llm_client,
)
from spectra_platform.services.ai.agents.base import (
    ActionRisk,
    AgentAction,
    AgentContext,
    ParallelToolAction,
)
from spectra_platform.services.ai.agents.scope import ScopeAction, ScopeAgent, ScopeInput
from spectra_platform.services.ai.agents.tool_selector import (
    ToolSelectorAgent,
    ToolSelectorInput,
    ToolSelectorOutput,
)
from spectra_platform.services.ai.consensus import (
    ConsensusStatus,
    VotingConfig,
    VotingSystem,
)
from spectra_tools_core.models import (
    RegisteredTool,
    ToolCategory,
    ToolConfig,
    ToolStatus,
)
from tests.mocks.llm import MockLLMClient

# --- Fixtures ---


@pytest.fixture
def mock_llm():
    """Create a mock LLM client."""
    return MockLLMClient()


@pytest.fixture
def mock_registry():
    """Create a mock tool registry."""
    registry = MagicMock()

    # Create some mock tools
    nmap_config = ToolConfig(
        id="nmap",
        name="Nmap",
        version="1.0.0",
        category=ToolCategory.DISCOVERY,
        description="Nmap scanner",
        execution={"command": "nmap", "args_template": ""},
    )
    naabu_config = ToolConfig(
        id="naabu",
        name="Naabu",
        version="1.0.0",
        category=ToolCategory.DISCOVERY,
        description="Naabu scanner",
        execution={"command": "naabu", "args_template": ""},
    )

    tools = [
        RegisteredTool(config=nmap_config, status=ToolStatus.READY),
        RegisteredTool(config=naabu_config, status=ToolStatus.READY),
    ]

    registry.get_available_tools.return_value = tools
    registry.list_tools.return_value = tools
    registry.sync_status_from_cache = AsyncMock()
    registry.get_tool.side_effect = lambda x: next((t for t in tools if t.config.id == x), None)

    return registry


@pytest.fixture
def agent_context():
    """Create a test agent context."""
    return AgentContext(
        mission_id="test-mission-1",
        session_id="test-session-123",
        target="192.168.1.1",
        mission="Test security assessment",
        phase="discovery",
        stealth_mode=False,
        max_concurrency=3,
    )


# --- LLM Client Tests ---


class TestMockLLMClient:
    """Tests for MockLLMClient."""

    @pytest.mark.asyncio
    async def test_generate_returns_response(self, mock_llm):
        """Test that generate returns an LLMResponse."""
        response = await mock_llm.generate("Test prompt")

        assert isinstance(response, LLMResponse)
        assert response.content == "Mock response"
        assert response.provider == "mock"

    @pytest.mark.asyncio
    async def test_generate_cycles_responses(self):
        """Test that multiple responses are cycled."""
        llm = MockLLMClient(responses=["First", "Second", "Third"])

        r1 = await llm.generate("prompt")
        r2 = await llm.generate("prompt")
        r3 = await llm.generate("prompt")
        r4 = await llm.generate("prompt")  # Should cycle back

        assert r1.content == "First"
        assert r2.content == "Second"
        assert r3.content == "Third"
        assert r4.content == "First"

    @pytest.mark.asyncio
    async def test_generate_structured_with_preset(self):
        """Test structured generation with preset responses."""

        class TestModel(BaseModel):
            name: str
            value: int

        llm = MockLLMClient(structured_responses={"TestModel": {"name": "test", "value": 42}})

        result = await llm.generate_structured("prompt", TestModel)

        assert isinstance(result, TestModel)
        assert result.name == "test"
        assert result.value == 42

    @pytest.mark.asyncio
    async def test_generate_structured_default(self):
        """Test structured generation with auto-generated defaults."""

        class SimpleModel(BaseModel):
            title: str
            count: int
            active: bool

        llm = MockLLMClient()
        result = await llm.generate_structured("prompt", SimpleModel)

        assert isinstance(result, SimpleModel)
        assert result.title == "mock_title"
        assert result.count == 0
        assert result.active is False

    @pytest.mark.asyncio
    async def test_call_history_tracking(self, mock_llm):
        """Test that calls are tracked."""
        await mock_llm.generate("First prompt", system_prompt="System 1")
        await mock_llm.generate("Second prompt")

        assert len(mock_llm.call_history) == 2
        assert mock_llm.call_history[0]["prompt"] == "First prompt"
        assert mock_llm.call_history[0]["system_prompt"] == "System 1"

    @pytest.mark.asyncio
    async def test_health_check(self, mock_llm):
        """Test health check always returns True for mock."""
        assert await mock_llm.health_check() is True


class TestLLMFactory:
    """Tests for the LLM factory function (TensorZero router)."""

    def test_get_default_returns_tensorzero_router(self):
        """Factory returns a TensorZero router."""
        from spectra_ai.router import TensorZeroRouter

        client = get_llm_client()
        assert isinstance(client, TensorZeroRouter)

    def test_get_with_provider_arg_returns_tensorzero(self):
        """Any provider string still returns the TensorZero router."""
        from spectra_ai.router import TensorZeroRouter

        client = get_llm_client("openai")
        assert isinstance(client, TensorZeroRouter)

    def test_client_has_generate_method(self):
        """Returned client exposes the standard generate interface."""
        client = get_llm_client()
        assert hasattr(client, "generate")

    def test_custom_gateway_url(self):
        """Factory accepts a custom gateway_url kwarg."""
        from spectra_ai.router import TensorZeroRouter

        client = get_llm_client(gateway_url="http://custom:3000")
        assert isinstance(client, TensorZeroRouter)


# --- Agent Tests ---


class TestScopeAgent:
    """Tests for ScopeAgent."""

    @pytest.mark.asyncio
    async def test_parse_single_ip(self, mock_llm, agent_context):
        """Test parsing a single IP address."""
        agent = ScopeAgent(mock_llm)
        input_data = ScopeInput(
            raw_input="Scan 192.168.1.100",
            include_subdomains=True,
            max_hosts=256,
        )

        result = await agent.execute(agent_context, input_data)

        assert result.success is True
        assert result.action is not None
        assert isinstance(result.action, ScopeAction)
        assert len(result.action.targets) >= 1

        ip_targets = [t for t in result.action.targets if t.target_type == "ip"]
        assert any(t.value == "192.168.1.100" for t in ip_targets)

    @pytest.mark.asyncio
    async def test_parse_cidr(self, mock_llm, agent_context):
        """Test parsing a CIDR range."""
        agent = ScopeAgent(mock_llm)
        input_data = ScopeInput(
            raw_input="Scan 10.0.0.0/24",
            include_subdomains=True,
            max_hosts=256,
        )

        result = await agent.execute(agent_context, input_data)

        assert result.success is True
        assert isinstance(result.action, ScopeAction)
        cidr_targets = [t for t in result.action.targets if t.target_type == "cidr"]
        assert len(cidr_targets) >= 1
        assert cidr_targets[0].value == "10.0.0.0/24"

    @pytest.mark.asyncio
    async def test_parse_domain(self, mock_llm, agent_context):
        """Test parsing a domain name."""
        agent = ScopeAgent(mock_llm)
        input_data = ScopeInput(
            raw_input="Assess security of example.com",
            include_subdomains=True,
            max_hosts=256,
        )

        result = await agent.execute(agent_context, input_data)

        assert result.success is True
        assert isinstance(result.action, ScopeAction)
        domain_targets = [t for t in result.action.targets if t.target_type == "domain"]
        assert any(t.value == "example.com" for t in domain_targets)

    @pytest.mark.asyncio
    async def test_parse_url(self, mock_llm, agent_context):
        """Test parsing a URL."""
        agent = ScopeAgent(mock_llm)
        input_data = ScopeInput(
            raw_input="Test https://api.example.com/v1",
            include_subdomains=True,
            max_hosts=256,
        )

        result = await agent.execute(agent_context, input_data)

        assert result.success is True
        assert isinstance(result.action, ScopeAction)
        url_targets = [t for t in result.action.targets if t.target_type == "url"]
        assert len(url_targets) >= 1

    @pytest.mark.asyncio
    async def test_empty_input_fails(self, mock_llm, agent_context):
        """Test that empty input returns no targets."""
        agent = ScopeAgent(mock_llm)
        input_data = ScopeInput(
            raw_input="Hello world",
            include_subdomains=True,
            max_hosts=256,
        )  # No targets

        result = await agent.execute(agent_context, input_data)

        # Should succeed but with no valid targets
        assert result.action is not None
        assert isinstance(result.action, ScopeAction)
        assert len(result.action.targets) == 0


class TestToolSelectorAgent:
    """Tests for ToolSelectorAgent."""

    @pytest.mark.asyncio
    async def test_selects_tool_for_discovery(self, mock_llm, agent_context, mock_registry):
        """Test tool selection for discovery phase."""
        # Configure mock to return valid tool selection
        mock_llm.structured_responses["ToolSelectorOutput"] = {
            "tool_name": "nmap",
            "target": "192.168.1.1",
            "tool_args": {},
            "confidence": 0.9,
            "risk_level": "low",
            "reasoning": "Nmap is ideal for port scanning",
            "alternatives": ["naabu"],
            "estimated_duration": 60,
            "skip_reason": None,
        }

        agent = ToolSelectorAgent(mock_llm)
        agent_context.phase = "discovery"

        input_data = ToolSelectorInput(
            current_phase="discovery",
            target="192.168.1.1",
            target_type="ip",
            user_preference=None,
        )

        with patch(
            "spectra_platform.services.ai.agents.tool_selector.get_registry",
            return_value=mock_registry,
        ):
            result = await agent.execute(agent_context, input_data)

        assert result.success is True
        assert result.action is not None
        # May return ParallelToolAction (nmap+naabu group) or ToolSelectorOutput
        assert isinstance(result.action, (ToolSelectorOutput, ParallelToolAction))
        if isinstance(result.action, ToolSelectorOutput):
            assert result.action.tool_name in ["nmap", "naabu"]
        else:
            tool_names = {t.tool_name for t in result.action.tools}
            assert tool_names & {"nmap", "naabu"}

    @pytest.mark.asyncio
    async def test_respects_user_preference(self, mock_llm, agent_context, mock_registry):
        """Test that user tool preference is respected."""
        # Configure mock LLM to return valid response
        mock_llm.structured_responses["ToolSelectorOutput"] = {
            "action_type": "run_tool",
            "tool_name": "naabu",
            "tool_args": {},
            "target": "192.168.1.1",
            "estimated_duration": 60,
            "confidence": 0.9,
            "risk_level": "low",
            "reasoning": "User requested naabu",
            "alternatives": [],
            "skip_reason": None,
        }

        agent = ToolSelectorAgent(mock_llm)

        input_data = ToolSelectorInput(
            current_phase="discovery",
            target="192.168.1.1",
            target_type="ip",
            user_preference="naabu",
        )

        with patch(
            "spectra_platform.services.ai.agents.tool_selector.get_registry",
            return_value=mock_registry,
        ):
            result = await agent.execute(agent_context, input_data)

        assert result.success is True
        assert isinstance(result.action, ToolSelectorOutput)
        assert result.action.tool_name == "naabu"

    @pytest.mark.asyncio
    async def test_skips_already_run_tools(self, mock_llm, agent_context, mock_registry):
        """Test that already-run tools are skipped."""
        agent = ToolSelectorAgent(mock_llm)

        input_data = ToolSelectorInput(
            current_phase="discovery",
            target="192.168.1.1",
            target_type="ip",
            tools_already_run=["naabu", "nmap"],  # All discovery tools in mock registry
            user_preference=None,
        )

        with patch(
            "spectra_platform.services.ai.agents.tool_selector.get_registry",
            return_value=mock_registry,
        ):
            result = await agent.execute(agent_context, input_data)

        assert result.success is True
        assert isinstance(result.action, ToolSelectorOutput)
        assert result.action.skip_reason == "phase_complete"


# --- Consensus Tests ---


class TestVotingSystem:
    """Tests for VotingSystem."""

    @pytest.fixture
    def voting_system(self, mock_llm):
        """Create a voting system with mock LLM."""
        config = VotingConfig(
            num_voters=3,
            k_threshold=2,
            min_confidence=0.6,
        )
        return VotingSystem(mock_llm, config)

    def test_low_risk_skips_voting(self, voting_system):
        """Test that low-risk actions skip voting."""
        action = AgentAction(
            action_type="test",
            confidence=0.9,
            risk_level=ActionRisk.LOW,
            reasoning="Test action",
        )

        assert voting_system.requires_voting(action) is False

    def test_high_risk_requires_voting(self, voting_system):
        """Test that high-risk actions require voting."""
        action = AgentAction(
            action_type="exploit",
            confidence=0.8,
            risk_level=ActionRisk.HIGH,
            reasoning="Exploitation attempt",
        )

        assert voting_system.requires_voting(action) is True

    def test_critical_requires_human(self, voting_system):
        """Test that critical actions require human approval."""
        action = AgentAction(
            action_type="dangerous",
            confidence=0.9,
            risk_level=ActionRisk.CRITICAL,
            reasoning="Dangerous action",
        )

        assert voting_system.requires_human_approval(action) is True

    @pytest.mark.asyncio
    async def test_vote_on_low_risk_auto_approves(self, voting_system):
        """Test that low-risk actions are auto-approved."""
        action = AgentAction(
            action_type="scan",
            confidence=0.9,
            risk_level=ActionRisk.LOW,
            reasoning="Simple scan",
        )

        result = await voting_system.vote_on_action(action)

        assert result.status == ConsensusStatus.APPROVED
        assert result.final_decision is True

    @pytest.mark.asyncio
    async def test_vote_on_critical_escalates(self, voting_system):
        """Test that critical actions escalate to human."""
        action = AgentAction(
            action_type="drop_database",
            confidence=0.9,
            risk_level=ActionRisk.CRITICAL,
            reasoning="Database operation",
        )

        result = await voting_system.vote_on_action(action)

        assert result.status == ConsensusStatus.PENDING_HUMAN

    @pytest.mark.asyncio
    async def test_approval_request_format(self, voting_system):
        """Test the approval request format."""
        action = AgentAction(
            action_type="exploit",
            confidence=0.8,
            risk_level=ActionRisk.HIGH,
            reasoning="Test exploit",
        )

        request = await voting_system.request_human_approval(action)

        assert request["type"] == "approval_request"
        assert "action" in request
        assert "timeout_seconds" in request
