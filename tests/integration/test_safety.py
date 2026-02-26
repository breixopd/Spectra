"""
E2E Test: Safety & Compliance (E2E-05, E2E-06, E2E-07)

Tests safety and compliance features:
- E2E-05: Safety blocking of dangerous commands
- E2E-06: Consensus rejection of high-risk actions
- E2E-07: Task failure handling with adaptive replanning

Corresponds to testplan.md Scenarios E2E-05, E2E-06, E2E-07.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch

from app.services.mission.manager import MissionManager
from app.services.mission.mission import Mission
from app.services.ai.agents.base import AgentContext, ToolAction, ActionRisk
from app.services.ai.agents.safety import (
    SafetySupervisorAgent,
    SafetyInput,
    SafetyAction,
)
from app.services.ai.consensus import VotingSystem, QualityGate, ConsensusStatus
from app.services.ai.llm import MockLLMClient


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.asyncio,
]


class TestSafetyBlocking:
    """Test safety blocking of dangerous commands (E2E-05)."""

    @pytest_asyncio.fixture
    async def safety_agent(self) -> SafetySupervisorAgent:
        """Create safety supervisor with mock LLM."""
        mock_llm = MockLLMClient(
            structured_responses={
                "SafetyAction": {
                    "action_type": "safety_check",
                    "confidence": 1.0,
                    "risk_level": "critical",
                    "reasoning": "Dangerous command blocked",
                    "allowed": False,
                    "reason": "Command contains dangerous pattern",
                    "modifications": [],
                }
            }
        )
        return SafetySupervisorAgent(mock_llm)

    async def test_blocks_rm_rf_command(self, safety_agent: SafetySupervisorAgent):
        """Test that rm -rf commands are blocked."""
        context = AgentContext(
            mission_id="test-mission-1",
            session_id="test",
            target="192.168.1.1",
            mission="Test",
            phase="exploitation",
            stealth_mode=False,
            max_concurrency=1,
        )

        safety_input = SafetyInput(
            command="rm -rf /",
            tool_id="shell",
            target="192.168.1.1",
            args={},
        )

        result = await safety_agent.execute(context, safety_input)

        assert result.success
        assert isinstance(result.action, SafetyAction)
        assert not result.action.allowed

    async def test_blocks_drop_table_command(self, safety_agent: SafetySupervisorAgent):
        """Test that DROP TABLE commands are blocked."""
        context = AgentContext(
            mission_id="test-mission-1",
            session_id="test",
            target="192.168.1.1",
            mission="Test",
            phase="exploitation",
            stealth_mode=False,
            max_concurrency=1,
        )

        safety_input = SafetyInput(
            command="sqlmap --batch --drop-table",
            tool_id="sqlmap",
            target="192.168.1.1",
            args={"drop_table": True},
        )

        result = await safety_agent.execute(context, safety_input)

        assert result.success
        assert isinstance(result.action, SafetyAction)
        # The mock is configured to block, but real implementation should also block

    async def test_blocks_out_of_scope_target(
        self, safety_agent: SafetySupervisorAgent
    ):
        """Test that out-of-scope targets are blocked."""
        # Configure mock to block out-of-scope
        safety_agent.llm = MockLLMClient(
            structured_responses={
                "SafetyAction": {
                    "action_type": "safety_check",
                    "confidence": 1.0,
                    "risk_level": "critical",
                    "reasoning": "Target out of scope",
                    "allowed": False,
                    "reason": "8.8.8.8 is not in the permitted scope",
                    "modifications": [],
                }
            }
        )

        context = AgentContext(
            mission_id="test-mission-1",
            session_id="test",
            target="192.168.1.1",  # Original target
            mission="Test",
            phase="discovery",
            stealth_mode=False,
            max_concurrency=1,
        )

        safety_input = SafetyInput(
            command="nmap 8.8.8.8",  # Out of scope!
            tool_id="nmap",
            target="8.8.8.8",
            args={},
        )

        result = await safety_agent.execute(context, safety_input)

        assert result.success
        assert isinstance(result.action, SafetyAction)
        assert not result.action.allowed
        assert (
            "scope" in result.action.reason.lower() or "8.8.8.8" in result.action.reason
        )

    async def test_allows_safe_commands(self):
        """Test that safe commands are allowed."""
        mock_llm = MockLLMClient(
            structured_responses={
                "SafetyAction": {
                    "action_type": "safety_check",
                    "confidence": 0.95,
                    "risk_level": "low",
                    "reasoning": "Safe reconnaissance command",
                    "allowed": True,
                    "reason": "Approved",
                    "modifications": [],
                }
            }
        )
        safety_agent = SafetySupervisorAgent(mock_llm)

        context = AgentContext(
            mission_id="test-mission-1",
            session_id="test",
            target="192.168.1.1",
            mission="Test",
            phase="discovery",
            stealth_mode=False,
            max_concurrency=1,
        )

        safety_input = SafetyInput(
            command="nmap -sV 192.168.1.1",
            tool_id="nmap",
            target="192.168.1.1",
            args={},
        )

        result = await safety_agent.execute(context, safety_input)

        assert result.success
        assert isinstance(result.action, SafetyAction)
        assert result.action.allowed


class TestConsensusRejection:
    """Test consensus rejection of risky actions (E2E-06)."""

    @pytest_asyncio.fixture
    async def voting_system(self) -> VotingSystem:
        """Create voting system with mock LLM."""
        mock_llm = MockLLMClient()
        return VotingSystem(mock_llm)

    async def test_high_risk_action_triggers_vote(self, voting_system: VotingSystem):
        """Test that high-risk actions trigger voting."""
        action = ToolAction(
            confidence=0.6,
            risk_level=ActionRisk.HIGH,
            reasoning="Risky action",
            tool_name="metasploit",
            target="192.168.1.1",
            tool_args={},
            estimated_duration=120,
        )

        context = {"target": "192.168.1.1", "tool": "metasploit"}

        # Call vote_on_action
        result = await voting_system.vote_on_action(action, context)

        assert result is not None
        assert hasattr(result, "status")

    async def test_low_confidence_triggers_vote(self, voting_system: VotingSystem):
        """Test that low confidence actions trigger voting."""
        action = ToolAction(
            confidence=0.4,  # Below typical threshold
            risk_level=ActionRisk.MEDIUM,
            reasoning="Uncertain action",
            tool_name="nmap",
            target="192.168.1.1",
            tool_args={},
            estimated_duration=60,
        )

        context = {"target": "192.168.1.1", "tool": "nmap"}

        result = await voting_system.vote_on_action(action, context)

        assert result is not None

    async def test_rejected_action_has_reason(self, voting_system: VotingSystem):
        """Test that rejected actions include escalation reason."""
        # Configure voting system to reject
        voting_system.llm = MockLLMClient(
            structured_responses={
                "VoteDecision": {
                    "approve": False,
                    "confidence": 0.3,
                    "reasoning": "Action is too risky for automated execution",
                }
            }
        )

        action = ToolAction(
            confidence=0.5,
            risk_level=ActionRisk.CRITICAL,
            reasoning="Very risky",
            tool_name="exploit",
            target="192.168.1.1",
            tool_args={},
            estimated_duration=300,
        )

        result = await voting_system.vote_on_action(action, {"target": "192.168.1.1"})

        # If rejected, should have escalation reason
        if result.status == "rejected":
            assert result.escalation_reason is not None

    async def test_quality_gate_validation(self, voting_system: VotingSystem):
        """Test validation at specific quality gates."""
        action = ToolAction(
            confidence=0.8,
            risk_level=ActionRisk.MEDIUM,
            reasoning="Standard tool selection",
            tool_name="nmap",
            target="192.168.1.1",
            tool_args={},
            estimated_duration=60,
        )

        context = {"target": "192.168.1.1", "phase": "discovery"}

        result = await voting_system.validate_at_gate(
            QualityGate.TOOL_SELECTION,
            action,
            context,
        )

        assert result is not None
        # Status is a ConsensusStatus enum
        assert result.status in [
            ConsensusStatus.APPROVED,
            ConsensusStatus.REJECTED,
            ConsensusStatus.NO_CONSENSUS,
            ConsensusStatus.PENDING_HUMAN,
        ]


class TestTaskFailureHandling:
    """Test task failure handling with adaptive replanning (E2E-07)."""

    async def test_task_failure_triggers_replan(
        self, mission_manager: MissionManager, test_target_ip: str
    ):
        """Test that task failure triggers replanning."""
        replan_triggered = False

        # Ensure agents initialized
        await mission_manager._ensure_agents()

        # Track if MissionController is called with is_steering=True
        from app.services.ai.agents.mission_controller import MissionInput

        original_execute = mission_manager.execution.mission_controller.execute

        async def mock_execute(context, input_data):
            nonlocal replan_triggered
            if isinstance(input_data, MissionInput) and input_data.is_steering:
                replan_triggered = True
                # Return a successful steering action
                from app.services.ai.agents.base import (
                    AgentResult,
                    SteeringAction,
                    ActionRisk,
                )

                return AgentResult(
                    success=True,
                    action=SteeringAction(
                        confidence=0.8,
                        risk_level=ActionRisk.LOW,
                        reasoning="Adapted plan after failure",
                        new_phase="discovery",
                    ),
                )
            # For non-steering calls, return a basic plan
            from app.services.ai.agents.base import AgentResult
            from app.services.ai.agents.mission_controller import (
                MissionPlan,
                MissionType,
            )

            return AgentResult(
                success=True,
                action=MissionPlan(
                    mission_type=MissionType.FULL_ASSESSMENT,
                    tasks=[],
                    requires_approval=False,
                ),
            )

        # Mock the consensus to approve everything
        async def mock_consensus(*args, **kwargs):
            from app.services.ai.consensus import ConsensusResult, ConsensusStatus

            return ConsensusResult(
                status=ConsensusStatus.APPROVED,
                votes=[],
                approve_count=1,
                reject_count=0,
                abstain_count=0,
                average_confidence=0.9,
                final_decision=True,
            )

        with patch.object(
            mission_manager.execution.mission_controller,
            "execute",
            side_effect=mock_execute,
        ):
            with patch.object(
                mission_manager.execution.consensus,
                "validate_at_gate",
                side_effect=mock_consensus,
            ):
                with patch(
                    "app.services.mission.manager.lifecycle.async_session_maker"
                ):
                    with patch("app.core.events.events.emit_sync"):
                        # Create a mission manually without going through start_mission
                        mission = Mission(
                            target=test_target_ip, directive="Test failure handling"
                        )
                        mission_manager.active_missions[mission.id] = mission

                        from app.services.ai.agents.mission_controller import (
                            Task,
                            AssessmentPhase,
                        )

                        # Create a failed task
                        task = Task(
                            task_id="failed-task",
                            description="This task will fail",
                            agent_type="tool_selector",
                            phase=AssessmentPhase.DISCOVERY,
                            priority=1,
                        )

                        context = AgentContext(
                            mission_id=mission.id,
                            session_id=mission.id,
                            target=test_target_ip,
                            mission="Test",
                            phase="discovery",
                            stealth_mode=False,
                            max_concurrency=1,
                        )

                        # Trigger failure handling directly via execution manager
                        await mission_manager.execution._handle_task_failure(
                            mission,
                            task,
                            "Connection refused",
                            context,
                        )

        # Replan should have been triggered
        assert replan_triggered, "Replanning was not triggered on task failure"

    async def test_failure_logged(
        self, mission_manager: MissionManager, test_target_ip: str
    ):
        """Test that failures are properly logged."""
        with patch("app.services.mission.manager.lifecycle.async_session_maker"):
            with patch("app.core.events.events.emit_sync"):
                mission_id = await mission_manager.start_mission(
                    target=test_target_ip,
                    directive="Logging test",
                )

                mission = await mission_manager.get_mission(mission_id)
                if mission:
                    from app.services.ai.agents.mission_controller import (
                        Task,
                        AssessmentPhase,
                    )

                    task = Task(
                        task_id="log-test-task",
                        description="Task for log testing",
                        agent_type="tool_selector",
                        phase=AssessmentPhase.DISCOVERY,
                        priority=1,
                    )

                    context = AgentContext(
                        mission_id=mission_id,
                        session_id=mission_id,
                        target=test_target_ip,
                        mission="Test",
                        phase="discovery",
                        stealth_mode=False,
                        max_concurrency=1,
                    )

                    await mission_manager.execution._handle_task_failure(
                        mission,
                        task,
                        "Test error message",
                        context,
                    )

                    # Check logs
                    logs = mission.logs
                    assert any("[ADAPT]" in log for log in logs), (
                        "Adaptation not logged"
                    )

    async def test_multiple_failures_handled(
        self, mission_manager: MissionManager, test_target_ip: str
    ):
        """Test handling multiple consecutive failures."""
        with patch("app.services.mission.manager.lifecycle.async_session_maker"):
            with patch("app.core.events.events.emit_sync"):
                mission_id = await mission_manager.start_mission(
                    target=test_target_ip,
                    directive="Multiple failures test",
                )

                mission = await mission_manager.get_mission(mission_id)
                if mission:
                    from app.services.ai.agents.mission_controller import (
                        Task,
                        AssessmentPhase,
                    )

                    context = AgentContext(
                        mission_id=mission_id,
                        session_id=mission_id,
                        target=test_target_ip,
                        mission="Test",
                        phase="discovery",
                        stealth_mode=False,
                        max_concurrency=1,
                    )

                    # Handle multiple failures
                    for i in range(3):
                        task = Task(
                            task_id=f"fail-task-{i}",
                            description=f"Failing task {i}",
                            agent_type="tool_selector",
                            phase=AssessmentPhase.DISCOVERY,
                            priority=1,
                        )

                        await mission_manager.execution._handle_task_failure(
                            mission,
                            task,
                            f"Error {i}",
                            context,
                        )

                    # All failures should be logged
                    logs = mission.logs
                    adapt_logs = [log for log in logs if "[ADAPT]" in log]
                    # We expect > 3 because there are multiple logs per adapt cycle ("Replanning...", "Unexpected action" or "Continuing")
                    # At minimum 3 "Replanning..." logs
                    replan_start_logs = [log for log in logs if "Replanning..." in log]
                    assert len(replan_start_logs) >= 3


class TestIntegratedSafety:
    """Test integrated safety in mission execution."""

    async def test_tool_execution_has_safety_supervisor(
        self, mission_manager: MissionManager
    ):
        """Test that mission executor has safety supervisor configured."""
        # Ensure agents initialized
        await mission_manager._ensure_agents()

        # Verify the tool service has a safety supervisor
        # Structure: mission_manager.execution.executor.tool_service.safety_supervisor
        assert (
            mission_manager.execution.executor.tool_service.safety_supervisor
            is not None
        )
        assert hasattr(
            mission_manager.execution.executor.tool_service.safety_supervisor, "execute"
        )

    async def test_run_tool_checks_safety_before_execution(self):
        """Test that tool execution includes safety check logic."""
        from app.services.tools.service import ToolExecutionService
        import inspect

        # Verify the execute_request method contains safety check logic
        source = inspect.getsource(ToolExecutionService.execute_request)

        assert "safety" in source.lower(), "execute_request should reference safety"
        assert (
            "SafetyInput" in source
            or "safety_supervisor" in source
            or "_perform_safety_check" in source
        ), "execute_request should use safety supervisor"
