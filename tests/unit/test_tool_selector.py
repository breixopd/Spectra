"""
Tests for Tool Selector Agent with edge cases and error handling.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.agents.base import ActionRisk, AgentContext
from app.services.ai.agents.tool_selector import (
    ToolSelectorAgent,
    ToolSelectorInput,
    ToolSelectorOutput,
)
from app.services.tools.models import RiskLevel
from tests.mocks.llm import MockLLMClient


class TestToolSelectorInput:
    """Tests for ToolSelectorInput validation."""

    def test_valid_input(self):
        """Valid input should create successfully."""
        input_data = ToolSelectorInput(
            current_phase="discovery",
            target="192.168.1.1",
            target_type="ip",
            user_preference=None,
            required_capability=None,
        )

        assert input_data.current_phase == "discovery"
        assert input_data.target == "192.168.1.1"
        assert input_data.target_type == "ip"

    def test_default_values(self):
        """Default values should be set correctly."""
        input_data = ToolSelectorInput(
            current_phase="enumeration",
            target="example.com",
            target_type="domain",
            user_preference=None,
            required_capability=None,
        )

        assert input_data.known_services == []
        assert input_data.known_vulns == []
        assert input_data.tools_already_run == []
        assert input_data.user_preference is None
        assert input_data.required_capability is None
        assert input_data.tags_filter == []

    def test_with_all_fields(self):
        """Input with all fields should work."""
        input_data = ToolSelectorInput(
            current_phase="exploitation",
            target="https://target.com",
            target_type="url",
            known_services=[{"port": 80, "service": "http"}],
            known_vulns=[{"name": "SQLi", "severity": "high"}],
            tools_already_run=["nmap", "nuclei"],
            user_preference="sqlmap",
            required_capability="sql_injection",
            tags_filter=["web", "injection"],
        )

        assert len(input_data.known_services) == 1
        assert len(input_data.known_vulns) == 1
        assert "nmap" in input_data.tools_already_run


class TestToolSelectorOutput:
    """Tests for ToolSelectorOutput validation."""

    def test_valid_output(self):
        """Valid output should create successfully."""
        output = ToolSelectorOutput(
            tool_name="nmap",
            target="192.168.1.1",
            tool_args={"ports": "1-1000", "scan_type": "-sV"},
            reasoning="Port scanning to discover services",
            confidence=0.9,
            risk_level=ActionRisk.LOW,
            estimated_duration=60,
        )

        assert output.tool_name == "nmap"
        assert output.target == "192.168.1.1"
        assert output.confidence == 0.9

    def test_skip_output(self):
        """Output indicating skip should work with empty tool_name."""
        output = ToolSelectorOutput(
            tool_name="",  # Empty string for skip
            target="192.168.1.1",
            reasoning="Phase complete",
            confidence=1.0,
            risk_level=ActionRisk.LOW,
            estimated_duration=0,
            skip_reason="All discovery tools have been run",
        )

        assert output.tool_name == ""
        assert output.skip_reason is not None

    def test_output_converts_to_tool_action(self):
        """Output should convert to ToolAction properly."""
        output = ToolSelectorOutput(
            tool_name="nuclei",
            target="https://example.com",
            tool_args={"templates": "cves/"},
            reasoning="Vulnerability scanning",
            confidence=0.85,
            risk_level=ActionRisk.LOW,
            estimated_duration=120,
        )

        # ToolSelectorOutput should have action_type
        assert output.action_type == "run_tool"


class TestToolSelectorPhaseCapabilities:
    """Tests for phase to capability mapping."""

    def test_discovery_phase_has_capabilities(self):
        """Discovery phase should have capabilities defined."""
        caps = ToolSelectorAgent.PHASE_CAPABILITIES.get("discovery", [])
        assert len(caps) > 0

    def test_enumeration_phase_has_capabilities(self):
        """Enumeration phase should have capabilities defined."""
        caps = ToolSelectorAgent.PHASE_CAPABILITIES.get("enumeration", [])
        assert len(caps) > 0

    def test_vulnerability_phase_has_capabilities(self):
        """Vulnerability phase should have capabilities defined."""
        caps = ToolSelectorAgent.PHASE_CAPABILITIES.get("vulnerability", [])
        assert len(caps) > 0

    def test_exploitation_phase_has_capabilities(self):
        """Exploitation phase should have capabilities defined."""
        caps = ToolSelectorAgent.PHASE_CAPABILITIES.get("exploitation", [])
        assert len(caps) > 0


class TestToolSelectorFallback:
    """Tests for fallback selection logic."""

    @pytest.fixture
    def agent(self):
        """Create a ToolSelectorAgent with mock LLM."""
        return ToolSelectorAgent(MockLLMClient())

    @pytest.fixture
    def mock_tools(self):
        """Create mock tool objects."""
        from app.services.tools.models import ToolCapability

        tools = []
        for tool_data in [
            {
                "id": "nmap",
                "caps": [ToolCapability.PORT_SCAN, ToolCapability.SERVICE_DETECTION],
                "risk": RiskLevel.LOW,
                "prereqs": [],
            },
            {
                "id": "nuclei",
                "caps": [ToolCapability.VULN_SCAN],
                "risk": RiskLevel.MEDIUM,
                "prereqs": ["nmap"],
            },
            {
                "id": "sqlmap",
                "caps": [ToolCapability.SQL_INJECTION],
                "risk": RiskLevel.HIGH,
                "prereqs": ["nuclei"],
            },
        ]:
            mock_tool = MagicMock()
            mock_tool.config.id = tool_data["id"]
            mock_tool.config.metadata.capabilities = tool_data["caps"]
            mock_tool.config.metadata.risk_level = tool_data["risk"]
            mock_tool.config.metadata.prerequisites = tool_data["prereqs"]
            tools.append(mock_tool)
        return tools

    def test_fallback_selects_a_tool(self, agent, mock_tools):
        """Fallback should select some tool."""
        input_data = ToolSelectorInput(
            current_phase="discovery",
            target="192.168.1.1",
            target_type="ip",
            tools_already_run=[],
            user_preference=None,
            required_capability=None,
        )

        result = agent._smart_fallback_selection(input_data, mock_tools)

        # Should select a tool
        assert result.tool_name in ["nmap", "nuclei", "sqlmap"]

    def test_fallback_prefers_lower_risk(self, agent):
        """Fallback should prefer lower risk tools."""
        from app.services.tools.models import ToolCapability

        # Create two tools with same capabilities but different risk
        mock_tool_low = MagicMock()
        mock_tool_low.config.id = "safe_scanner"
        mock_tool_low.config.metadata.capabilities = [ToolCapability.VULN_SCAN]
        mock_tool_low.config.metadata.risk_level = RiskLevel.LOW
        mock_tool_low.config.metadata.prerequisites = []

        mock_tool_high = MagicMock()
        mock_tool_high.config.id = "risky_scanner"
        mock_tool_high.config.metadata.capabilities = [ToolCapability.VULN_SCAN]
        mock_tool_high.config.metadata.risk_level = RiskLevel.HIGH
        mock_tool_high.config.metadata.prerequisites = []

        input_data = ToolSelectorInput(
            current_phase="vulnerability",
            target="192.168.1.1",
            target_type="ip",
            tools_already_run=[],
            user_preference=None,
            required_capability=None,
        )

        result = agent._smart_fallback_selection(input_data, [mock_tool_high, mock_tool_low])

        # Lower risk should be preferred
        assert result.tool_name == "safe_scanner"


class TestToolSelectorExecution:
    """Tests for full execution flow."""

    @pytest.fixture
    def mock_llm(self):
        """Create mock LLM that returns tool selection."""
        return MockLLMClient(
            structured_responses={
                "ToolSelectorOutput": {
                    "tool_name": "nmap",
                    "target": "192.168.1.1",
                    "tool_args": {"ports": "1-65535"},
                    "reasoning": "Full port scan needed",
                    "confidence": 0.9,
                    "action_type": "run_tool",
                    "risk_level": "low",
                }
            }
        )

    @pytest.fixture
    def context(self):
        """Create agent context."""
        return AgentContext(
            mission_id="test-mission-1",
            session_id="test-session",
            target="192.168.1.1",
            mission="Security assessment",
            phase="discovery",
            stealth_mode=False,
            max_concurrency=5,
        )

    @pytest.mark.asyncio
    async def test_execute_returns_result(self, mock_llm, context):
        """Execute should return a valid result."""
        from app.services.tools.models import ToolCapability

        agent = ToolSelectorAgent(mock_llm)

        input_data = ToolSelectorInput(
            current_phase="discovery",
            target="192.168.1.1",
            target_type="ip",
            user_preference=None,
            required_capability=None,
        )

        # Mock registry to return available tools
        with patch("app.services.ai.agents.tool_selector.get_registry") as mock_registry:
            mock_tool = MagicMock()
            mock_tool.is_available = True
            mock_tool.config.id = "nmap"
            mock_tool.config.metadata.capabilities = [ToolCapability.PORT_SCAN]
            mock_tool.config.metadata.ai_description = "Port scanner"
            mock_tool.config.metadata.use_cases = ["Discovery"]
            mock_tool.config.metadata.limitations = []
            mock_tool.config.metadata.risk_level = RiskLevel.LOW
            mock_tool.config.metadata.prerequisites = []
            mock_tool.config.metadata.tags = ["network"]
            mock_tool.config.metadata.categories = ["DISCOVERY"]
            mock_tool.config.get_ai_summary.return_value = (
                "**Nmap** (nmap)\nCategory: discovery\nDescription: Port scanner"
            )
            mock_tool.config.execution.min_timeout = 60
            mock_tool.config.execution.timeout = 300

            registry_instance = mock_registry.return_value
            registry_instance.get_tool.return_value = mock_tool
            registry_instance.list_tools.return_value = [mock_tool]
            registry_instance.sync_status_from_cache = AsyncMock()

            result = await agent.execute(context, input_data)

        assert result.success is True
        assert result.action is not None

    @pytest.mark.asyncio
    async def test_execute_with_no_available_tools(self, context):
        """Execute should handle no available tools gracefully."""
        agent = ToolSelectorAgent(MockLLMClient())

        input_data = ToolSelectorInput(
            current_phase="discovery",
            target="192.168.1.1",
            target_type="ip",
            user_preference=None,
            required_capability=None,
        )

        # Mock registry to return no tools
        with patch("app.services.ai.agents.tool_selector.get_registry") as mock_registry:
            mock_registry.return_value.list_tools.return_value = []

            result = await agent.execute(context, input_data)

        # Should skip since no tools available
        assert result.action is not None
        # ToolSelectorOutput has skip_reason attribute - cast to check
        from app.services.ai.agents.tool_selector import ToolSelectorOutput

        if isinstance(result.action, ToolSelectorOutput):
            assert result.action.skip_reason is not None


class TestToolSelectorStealthMode:
    """Tests for stealth mode handling."""

    @pytest.fixture
    def context_stealth(self):
        """Create stealth mode context."""
        return AgentContext(
            mission_id="test-mission-1",
            session_id="test-session",
            target="192.168.1.1",
            mission="Quiet assessment",
            phase="discovery",
            stealth_mode=True,
            max_concurrency=2,
        )

    def test_stealth_system_prompt_includes_stealth(self):
        """System prompt should mention stealth when enabled."""
        agent = ToolSelectorAgent(MockLLMClient())
        context = AgentContext(
            mission_id="test-mission-1",
            session_id="test",
            target="target.com",
            mission="Stealth scan",
            phase="discovery",
            stealth_mode=True,
            max_concurrency=1,
        )

        prompt = agent._build_system_prompt(context)

        assert "stealth" in prompt.lower() or "quiet" in prompt.lower() or "evasion" in prompt.lower()
