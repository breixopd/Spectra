"""
Comprehensive tests for agents with low coverage:
- ExploitCrafter
- VectorGeneratorAgent
- SafetySupervisorAgent
- PostExploitationAgent
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.ai.agents.base import (
    ActionRisk,
    AgentContext,
)
from app.services.ai.agents.exploit_crafter import (
    ExploitAction,
    ExploitCrafter,
    ExploitInput,
)
from app.services.ai.agents.post_exploitation import (
    PostExploitAction,
    PostExploitationAgent,
    PostExploitInput,
)
from app.services.ai.agents.safety import (
    SafetyInput,
    SafetySupervisorAgent,
)
from app.services.ai.agents.vector_generator import (
    VectorGeneratorAgent,
    VectorGeneratorInput,
    VectorGeneratorOutput,
)
from tests.mocks.llm import MockLLMClient

# --- Fixtures ---


@pytest.fixture
def context():
    """Minimal AgentContext for testing."""
    return AgentContext(mission_id="test")


@pytest.fixture
def mock_llm():
    return MockLLMClient()


# ===========================
# ExploitCrafter Tests
# ===========================


class TestExploitCrafter:
    """Tests for the ExploitCrafter agent."""

    @pytest.mark.asyncio
    async def test_execute_no_candidates(self, mock_llm, context):
        """When _find_exploit_candidates returns empty, execute returns error."""
        agent = ExploitCrafter(llm=mock_llm)

        with patch.object(
            agent, "_find_exploit_candidates", new_callable=AsyncMock, return_value=[]
        ):
            input_data = ExploitInput(target="10.0.0.1")
            result = await agent.execute(context, input_data)

        assert result.success is False
        assert result.error == "No suitable exploits found"

    @pytest.mark.asyncio
    async def test_execute_with_candidates_first_attempt(self, mock_llm, context):
        """First attempt selects candidate at index 0."""
        agent = ExploitCrafter(llm=mock_llm)

        candidates = [
            {"name": "exploit_a", "type": "cve"},
            {"name": "exploit_b", "type": "generic"},
        ]
        mock_action = ExploitAction(
            confidence=0.8,
            risk_level=ActionRisk.HIGH,
            reasoning="test",
            exploit_name="exploit_a",
            payload_type="reverse_tcp",
            configuration={"RHOST": "10.0.0.1"},
            attempt_number=1,
        )

        with (
            patch.object(
                agent,
                "_find_exploit_candidates",
                new_callable=AsyncMock,
                return_value=candidates,
            ),
            patch.object(
                agent,
                "_configure_exploit",
                new_callable=AsyncMock,
                return_value=mock_action,
            ),
        ):
            input_data = ExploitInput(target="10.0.0.1")
            result = await agent.execute(context, input_data)

        assert result.success is True
        assert result.metadata["selected_index"] == 0
        assert result.metadata["candidates"] == 2

    @pytest.mark.asyncio
    async def test_execute_rotates_candidates(self, mock_llm, context):
        """With previous exploit actions, attempt number increments and rotates candidates."""
        context.previous_actions = [
            {"action_type": "execute_exploit", "error": "Connection refused"},
        ]
        agent = ExploitCrafter(llm=mock_llm)

        candidates = [
            {"name": "exploit_a", "type": "cve"},
            {"name": "exploit_b", "type": "generic"},
        ]
        mock_action = ExploitAction(
            confidence=0.7,
            risk_level=ActionRisk.HIGH,
            reasoning="retry",
            exploit_name="exploit_b",
            payload_type="bind_tcp",
            configuration={},
            attempt_number=2,
        )

        with (
            patch.object(
                agent,
                "_find_exploit_candidates",
                new_callable=AsyncMock,
                return_value=candidates,
            ),
            patch.object(
                agent,
                "_configure_exploit",
                new_callable=AsyncMock,
                return_value=mock_action,
            ) as mock_cfg,
        ):
            input_data = ExploitInput(target="10.0.0.1")
            result = await agent.execute(context, input_data)

        assert result.success is True
        assert result.metadata["selected_index"] == 1
        call_kwargs = mock_cfg.call_args
        assert call_kwargs[1]["attempt"] == 2
        assert "Connection refused" in call_kwargs[1]["previous_error"]

    @pytest.mark.asyncio
    async def test_execute_wraps_around_candidates(self, mock_llm, context):
        """When attempt exceeds candidate count, wraps around via modulo."""
        context.previous_actions = [
            {"action_type": "execute_exploit", "error": "fail1"},
            {"action_type": "execute_exploit", "error": "fail2"},
        ]
        agent = ExploitCrafter(llm=mock_llm)
        candidates = [{"name": "only_one", "type": "cve"}]
        mock_action = ExploitAction(
            confidence=0.5,
            risk_level=ActionRisk.HIGH,
            reasoning="wrap",
            exploit_name="only_one",
            payload_type="reverse_tcp",
            configuration={},
            attempt_number=3,
        )

        with (
            patch.object(
                agent,
                "_find_exploit_candidates",
                new_callable=AsyncMock,
                return_value=candidates,
            ),
            patch.object(
                agent,
                "_configure_exploit",
                new_callable=AsyncMock,
                return_value=mock_action,
            ),
        ):
            result = await agent.execute(context, ExploitInput(target="10.0.0.1"))

        assert result.success is True
        assert result.metadata["selected_index"] == 0  # (3-1) % 1 == 0

    @pytest.mark.asyncio
    async def test_configure_exploit_via_llm(self, context):
        """_configure_exploit calls generate_structured and sets attempt_number."""
        llm = MockLLMClient(
            structured_responses={
                "ExploitAction": {
                    "confidence": 0.9,
                    "risk_level": "high",
                    "reasoning": "LLM chose this",
                    "exploit_name": "ms17_010",
                    "payload_type": "reverse_tcp",
                    "configuration": {"RHOST": "10.0.0.1"},
                    "attempt_number": 999,
                    "action_type": "execute_exploit",
                }
            }
        )
        agent = ExploitCrafter(llm=llm)
        candidate = {"name": "ms17_010", "type": "cve"}
        input_data = ExploitInput(target="10.0.0.1", service_info={"port": 445})

        action = await agent._configure_exploit(
            context, candidate, input_data, attempt=2
        )

        assert isinstance(action, ExploitAction)
        assert action.attempt_number == 2  # overridden by the method
        assert action.exploit_name == "ms17_010"

    @pytest.mark.asyncio
    async def test_configure_exploit_fallback_on_llm_failure(self, context):
        """When LLM raises, _configure_exploit returns a fallback ExploitAction."""
        llm = MockLLMClient()
        llm.generate_structured = AsyncMock(side_effect=RuntimeError("LLM down"))
        agent = ExploitCrafter(llm=llm)

        candidate = {"name": "fallback_exploit", "type": "generic"}
        input_data = ExploitInput(target="10.0.0.1", service_info={"port": 80})

        action = await agent._configure_exploit(
            context, candidate, input_data, attempt=1
        )

        assert isinstance(action, ExploitAction)
        assert action.exploit_name == "fallback_exploit"
        assert action.payload_type == "linux/x64/shell_reverse_tcp"
        assert action.configuration["RHOST"] == "10.0.0.1"
        assert action.configuration["RPORT"] == 80
        assert action.attempt_number == 1
        assert "Fallback" in action.reasoning

    @pytest.mark.asyncio
    async def test_verify_success_uid(self, mock_llm):
        agent = ExploitCrafter(llm=mock_llm)
        assert await agent.verify_success("10.0.0.1", "uid=0(root) gid=0(root)") is True

    @pytest.mark.asyncio
    async def test_verify_success_root_prompt(self, mock_llm):
        agent = ExploitCrafter(llm=mock_llm)
        assert await agent.verify_success("10.0.0.1", "root@server:~#") is True

    @pytest.mark.asyncio
    async def test_verify_success_meterpreter(self, mock_llm):
        agent = ExploitCrafter(llm=mock_llm)
        assert (
            await agent.verify_success("10.0.0.1", "Meterpreter session 1 opened")
            is True
        )

    @pytest.mark.asyncio
    async def test_verify_success_command_shell(self, mock_llm):
        agent = ExploitCrafter(llm=mock_llm)
        assert (
            await agent.verify_success("10.0.0.1", "Command shell opened at 10.0.0.1")
            is True
        )

    @pytest.mark.asyncio
    async def test_verify_success_administrator(self, mock_llm):
        agent = ExploitCrafter(llm=mock_llm)
        assert (
            await agent.verify_success("10.0.0.1", "Administrator session started")
            is True
        )

    @pytest.mark.asyncio
    async def test_verify_success_no_match(self, mock_llm):
        agent = ExploitCrafter(llm=mock_llm)
        assert await agent.verify_success("10.0.0.1", "Connection refused") is False

    @pytest.mark.asyncio
    async def test_verify_success_empty_output(self, mock_llm):
        agent = ExploitCrafter(llm=mock_llm)
        assert await agent.verify_success("10.0.0.1", "") is False


# ===========================
# VectorGeneratorAgent Tests
# ===========================


class TestVectorGeneratorAgent:
    """Tests for the VectorGeneratorAgent."""

    @pytest.mark.asyncio
    async def test_execute_generates_vectors(self, mock_llm, context):
        """execute returns success when _generate_with_llm succeeds."""
        agent = VectorGeneratorAgent(llm=mock_llm)

        mock_output = VectorGeneratorOutput(
            confidence=0.8,
            risk_level=ActionRisk.MEDIUM,
            reasoning="Generated vectors",
            vectors=[],
        )
        with patch.object(
            agent,
            "_generate_with_llm",
            new_callable=AsyncMock,
            return_value=mock_output,
        ):
            input_data = VectorGeneratorInput(
                target_type="service",
                target_data={"host": "10.0.0.1", "port": 22, "service": "ssh"},
            )
            result = await agent.execute(context, input_data)

        assert result.success is True
        assert result.action is not None
        assert isinstance(result.action, VectorGeneratorOutput)

    @pytest.mark.asyncio
    async def test_execute_with_empty_services(self, mock_llm, context):
        """execute with minimal target data still works."""
        agent = VectorGeneratorAgent(llm=mock_llm)

        mock_output = VectorGeneratorOutput(
            confidence=0.5,
            risk_level=ActionRisk.LOW,
            reasoning="No services",
            vectors=[],
        )
        with patch.object(
            agent,
            "_generate_with_llm",
            new_callable=AsyncMock,
            return_value=mock_output,
        ):
            input_data = VectorGeneratorInput(
                target_type="service",
                target_data={},
            )
            result = await agent.execute(context, input_data)

        assert result.success is True
        assert result.action.vectors == []

    @pytest.mark.asyncio
    async def test_execute_handles_llm_failure(self, mock_llm, context):
        """When _generate_with_llm raises, execute returns failure."""
        agent = VectorGeneratorAgent(llm=mock_llm)

        with patch.object(
            agent,
            "_generate_with_llm",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM error"),
        ):
            input_data = VectorGeneratorInput(
                target_type="service",
                target_data={"host": "10.0.0.1"},
            )
            result = await agent.execute(context, input_data)

        assert result.success is False
        assert "LLM error" in result.error


# ===========================
# SafetySupervisorAgent Tests
# ===========================


class TestSafetySupervisorAgent:
    """Tests for the SafetySupervisorAgent."""

    @pytest.mark.asyncio
    async def test_blocks_rm_rf_root(self, mock_llm, context):
        agent = SafetySupervisorAgent(llm=mock_llm)
        input_data = SafetyInput(
            command="rm -rf /",
            tool_id="shell",
            target="10.0.0.1",
        )
        result = await agent.execute(context, input_data)

        assert result.success is True
        assert result.action.allowed is False
        assert result.action.risk_level == ActionRisk.CRITICAL

    @pytest.mark.asyncio
    async def test_blocks_rm_rf_wildcard(self, mock_llm, context):
        agent = SafetySupervisorAgent(llm=mock_llm)
        input_data = SafetyInput(
            command="rm -rf /*",
            tool_id="shell",
            target="10.0.0.1",
        )
        result = await agent.execute(context, input_data)

        assert result.success is True
        assert result.action.allowed is False

    @pytest.mark.asyncio
    async def test_blocks_fork_bomb(self, mock_llm, context):
        agent = SafetySupervisorAgent(llm=mock_llm)
        input_data = SafetyInput(
            command=":(){  :|: & };:",
            tool_id="shell",
            target="10.0.0.1",
        )
        result = await agent.execute(context, input_data)

        assert result.success is True
        assert result.action.allowed is False

    @pytest.mark.asyncio
    async def test_blocks_mkfs(self, mock_llm, context):
        agent = SafetySupervisorAgent(llm=mock_llm)
        input_data = SafetyInput(
            command="mkfs.ext4 /dev/sda",
            tool_id="shell",
            target="10.0.0.1",
        )
        result = await agent.execute(context, input_data)

        assert result.success is True
        assert result.action.allowed is False

    @pytest.mark.asyncio
    async def test_blocks_overwrite_passwd(self, mock_llm, context):
        agent = SafetySupervisorAgent(llm=mock_llm)
        input_data = SafetyInput(
            command="echo hacked > /etc/passwd",
            tool_id="shell",
            target="10.0.0.1",
        )
        result = await agent.execute(context, input_data)

        assert result.success is True
        assert result.action.allowed is False

    @pytest.mark.asyncio
    async def test_blocks_dd_to_dev(self, mock_llm, context):
        agent = SafetySupervisorAgent(llm=mock_llm)
        input_data = SafetyInput(
            command="dd if=/dev/zero of=/dev/sda",
            tool_id="shell",
            target="10.0.0.1",
        )
        result = await agent.execute(context, input_data)

        assert result.success is True
        assert result.action.allowed is False

    @pytest.mark.asyncio
    async def test_allows_nmap_via_llm(self, context):
        """Safe commands pass regex blocklist and go through LLM evaluation."""
        llm = MockLLMClient(
            structured_responses={
                "SafetyAction": {
                    "confidence": 0.95,
                    "risk_level": "low",
                    "reasoning": "Standard nmap scan",
                    "allowed": True,
                    "reason": "Safe scanning command",
                    "action_type": "safety_check",
                }
            }
        )
        agent = SafetySupervisorAgent(llm=llm)
        input_data = SafetyInput(
            command="nmap -sV 10.0.0.1",
            tool_id="nmap",
            target="10.0.0.1",
        )
        result = await agent.execute(context, input_data)

        assert result.success is True
        assert result.action.allowed is True

    @pytest.mark.asyncio
    async def test_allows_curl_via_llm(self, context):
        llm = MockLLMClient(
            structured_responses={
                "SafetyAction": {
                    "confidence": 0.9,
                    "risk_level": "low",
                    "reasoning": "HTTP request",
                    "allowed": True,
                    "reason": "Safe HTTP request",
                    "action_type": "safety_check",
                }
            }
        )
        agent = SafetySupervisorAgent(llm=llm)
        input_data = SafetyInput(
            command="curl http://10.0.0.1",
            tool_id="curl",
            target="10.0.0.1",
        )
        result = await agent.execute(context, input_data)

        assert result.success is True
        assert result.action.allowed is True

    @pytest.mark.asyncio
    async def test_llm_failure_blocks_by_default(self, context):
        """When the LLM fails, the agent blocks the command as a safety measure."""
        llm = MockLLMClient()
        llm.generate_structured = AsyncMock(side_effect=RuntimeError("LLM crashed"))
        agent = SafetySupervisorAgent(llm=llm)

        input_data = SafetyInput(
            command="some-unknown-tool",
            tool_id="unknown",
            target="10.0.0.1",
        )
        result = await agent.execute(context, input_data)

        assert result.success is False
        assert result.action.allowed is False
        assert result.action.reason == "Internal error during safety check"


# ===========================
# PostExploitationAgent Tests
# ===========================


class TestPostExploitationAgent:
    """Tests for the PostExploitationAgent."""

    @pytest.mark.asyncio
    async def test_execute_generates_plan(self, context):
        """Successful LLM call returns a post-exploitation plan."""
        llm = MockLLMClient(
            structured_responses={
                "PostExploitAction": {
                    "confidence": 0.85,
                    "risk_level": "medium",
                    "reasoning": "Post-exploit plan generated",
                    "action_type": "post_exploit_plan",
                    "suggested_actions": ["whoami", "uname -a", "cat /etc/shadow"],
                    "persistence_methods": ["crontab"],
                    "exfiltration_targets": ["/etc/passwd"],
                }
            }
        )
        agent = PostExploitationAgent(llm=llm)
        input_data = PostExploitInput(
            target="10.0.0.1",
            access_level="root",
            system_info="Linux 5.4",
        )
        result = await agent.execute(context, input_data)

        assert result.success is True
        assert isinstance(result.action, PostExploitAction)
        assert "whoami" in result.action.suggested_actions
        assert "crontab" in result.action.persistence_methods

    @pytest.mark.asyncio
    async def test_execute_with_previous_findings(self, context):
        """Context previous_findings are included in the prompt."""
        context.previous_findings = [
            {"title": "Open SSH", "severity": "medium"},
            {"title": "Weak password", "severity": "high"},
        ]
        llm = MockLLMClient(
            structured_responses={
                "PostExploitAction": {
                    "confidence": 0.7,
                    "risk_level": "medium",
                    "reasoning": "Based on findings",
                    "action_type": "post_exploit_plan",
                    "suggested_actions": ["escalate"],
                    "persistence_methods": [],
                    "exfiltration_targets": [],
                }
            }
        )
        agent = PostExploitationAgent(llm=llm)
        input_data = PostExploitInput(target="10.0.0.1", access_level="user")
        result = await agent.execute(context, input_data)

        assert result.success is True
        # Verify the prompt included findings
        call = llm.call_history[0]
        assert "Open SSH" in call["prompt"]
        assert "Weak password" in call["prompt"]

    @pytest.mark.asyncio
    async def test_execute_with_llm_failure(self, context):
        """When LLM raises, execute returns failure."""
        llm = MockLLMClient()
        llm.generate_structured = AsyncMock(side_effect=RuntimeError("LLM unreachable"))
        agent = PostExploitationAgent(llm=llm)

        input_data = PostExploitInput(
            target="10.0.0.1",
            access_level="root",
        )
        result = await agent.execute(context, input_data)

        assert result.success is False
        assert "LLM unreachable" in result.error

    @pytest.mark.asyncio
    async def test_execute_no_previous_findings(self, context):
        """With empty previous_findings, prompt still contains 'None'."""
        llm = MockLLMClient(
            structured_responses={
                "PostExploitAction": {
                    "confidence": 0.6,
                    "risk_level": "low",
                    "reasoning": "No context",
                    "action_type": "post_exploit_plan",
                    "suggested_actions": [],
                    "persistence_methods": [],
                    "exfiltration_targets": [],
                }
            }
        )
        agent = PostExploitationAgent(llm=llm)
        input_data = PostExploitInput(target="10.0.0.1", access_level="user")
        result = await agent.execute(context, input_data)

        assert result.success is True
        call = llm.call_history[0]
        assert "None" in call["prompt"]
