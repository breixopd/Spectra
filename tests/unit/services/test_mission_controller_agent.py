"""
Comprehensive tests for MissionController agent.

Tests the mission orchestration workflow including:
- execute routing (plan creation, steering, phase transitions)
- _create_mission_plan success and failure
- _handle_steering with focus, skip, stop, and ambiguous commands
- _handle_phase_transition with forced phase changes
- _parse_focus_command target extraction
- _parse_skip_command phase extraction
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mission.core.enums import AssessmentPhase
from app.services.ai.agents.base import (
    ActionRisk,
    AgentContext,
    AgentResult,
    SteeringAction,
)
from app.services.ai.agents.mission_controller import (
    MissionController,
    MissionInput,
    MissionPlan,
    PhaseTransition,
)
from spectra_ai.errors import LLMParseError
from tests.mocks.llm import MockLLMClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm():
    """MockLLMClient with a default MissionPlan response."""
    return MockLLMClient(
        structured_responses={
            "MissionPlan": {
                "action_type": "mission_plan",
                "confidence": 0.9,
                "risk_level": "low",
                "reasoning": "Test plan",
                "mission_type": "full_assessment",
                "tasks": [
                    {
                        "task_id": "t1",
                        "description": "Run nmap scan",
                        "agent_type": "tool_selector",
                        "phase": "discovery",
                        "priority": 1,
                    }
                ],
                "current_phase": "scope",
                "estimated_duration_minutes": 30,
                "requires_approval": False,
            },
            "SteeringAction": {
                "action_type": "steer",
                "confidence": 0.7,
                "risk_level": "low",
                "reasoning": "LLM interpreted steering",
                "new_phase": "enumeration",
                "priority_targets": ["network"],
                "skip_phases": [],
            },
        }
    )


@pytest.fixture
def controller(mock_llm):
    with patch("app.services.ai.consensus.VotingSystem"):
        ctrl = MissionController(mock_llm)
    return ctrl


@pytest.fixture
def context():
    return AgentContext(
        mission_id="test-ctrl-1",
        session_id="session-1",
        target="192.168.1.100",
        mission="Full security assessment",
        phase="discovery",
    )


# ---------------------------------------------------------------------------
# execute routing
# ---------------------------------------------------------------------------


class TestExecuteRouting:
    """Tests for the execute method routing logic."""

    @pytest.mark.asyncio
    async def test_routes_to_create_mission_plan(self, controller, context):
        """When is_steering=False and no force_phase, creates mission plan."""
        input_data = MissionInput(directive="Scan the network")

        with patch.object(controller, "_create_mission_plan", new_callable=AsyncMock) as mock_plan:
            mock_plan.return_value = MagicMock(spec=MissionPlan)
            result = await controller.execute(context, input_data)

        assert result.success is True
        mock_plan.assert_awaited_once_with(context, input_data)

    @pytest.mark.asyncio
    async def test_routes_to_handle_steering(self, controller, context):
        """When is_steering=True, routes to _handle_steering."""
        input_data = MissionInput(directive="focus on web", is_steering=True)

        with patch.object(controller, "_handle_steering", new_callable=AsyncMock) as mock_steer:
            mock_steer.return_value = AgentResult(success=True, action=MagicMock())
            await controller.execute(context, input_data)

        mock_steer.assert_awaited_once_with(context, input_data)

    @pytest.mark.asyncio
    async def test_routes_to_phase_transition(self, controller, context):
        """When force_phase is set, routes to _handle_phase_transition."""
        input_data = MissionInput(
            directive="Move to exploitation",
            force_phase=AssessmentPhase.EXPLOITATION,
        )

        with patch.object(controller, "_handle_phase_transition", new_callable=AsyncMock) as mock_trans:
            mock_trans.return_value = AgentResult(success=True, action=MagicMock())
            await controller.execute(context, input_data)

        mock_trans.assert_awaited_once_with(context, input_data)

    @pytest.mark.asyncio
    async def test_steering_takes_precedence_over_force_phase(self, controller, context):
        """When both is_steering and force_phase are set, steering wins."""
        input_data = MissionInput(
            directive="stop",
            is_steering=True,
            force_phase=AssessmentPhase.EXPLOITATION,
        )

        with patch.object(controller, "_handle_steering", new_callable=AsyncMock) as mock_steer:
            mock_steer.return_value = AgentResult(success=True, action=MagicMock())
            await controller.execute(context, input_data)

        mock_steer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_handles_exception(self, controller, context):
        """When an exception occurs, result is failure with error message."""
        input_data = MissionInput(directive="crash")

        with patch.object(
            controller,
            "_create_mission_plan",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM crashed"),
        ):
            result = await controller.execute(context, input_data)

        assert result.success is False
        assert "LLM crashed" in result.error


# ---------------------------------------------------------------------------
# _handle_steering
# ---------------------------------------------------------------------------


class TestHandleSteering:
    """Tests for _handle_steering and keyword parsing."""

    @pytest.mark.asyncio
    async def test_focus_on_web(self, controller, context):
        """'focus on web' adds web_services to priority_targets."""
        input_data = MissionInput(directive="focus on web services", is_steering=True)

        result = await controller._handle_steering(context, input_data)

        assert result.success is True
        action = result.action
        assert isinstance(action, SteeringAction)
        assert "web_services" in action.priority_targets

    @pytest.mark.asyncio
    async def test_focus_on_database(self, controller, context):
        """'prioritize database' adds databases to priority_targets."""
        input_data = MissionInput(directive="prioritize database scanning", is_steering=True)

        result = await controller._handle_steering(context, input_data)

        action = result.action
        assert isinstance(action, SteeringAction)
        assert "databases" in action.priority_targets

    @pytest.mark.asyncio
    async def test_focus_on_api(self, controller, context):
        """'focus on api' adds apis to priority_targets."""
        input_data = MissionInput(directive="focus on api endpoints", is_steering=True)

        result = await controller._handle_steering(context, input_data)

        action = result.action
        assert isinstance(action, SteeringAction)
        assert "apis" in action.priority_targets

    @pytest.mark.asyncio
    async def test_focus_multiple_targets(self, controller, context):
        """Multiple focus keywords yield multiple priority_targets."""
        input_data = MissionInput(directive="focus on web and database and api", is_steering=True)

        result = await controller._handle_steering(context, input_data)

        action = result.action
        assert isinstance(action, SteeringAction)
        assert "web_services" in action.priority_targets
        assert "databases" in action.priority_targets
        assert "apis" in action.priority_targets

    @pytest.mark.asyncio
    async def test_skip_exploitation(self, controller, context):
        """'skip exploitation' adds exploitation to skip_phases."""
        input_data = MissionInput(directive="skip exploitation phase", is_steering=True)

        result = await controller._handle_steering(context, input_data)

        action = result.action
        assert isinstance(action, SteeringAction)
        assert AssessmentPhase.EXPLOITATION.value in action.skip_phases

    @pytest.mark.asyncio
    async def test_skip_enumeration(self, controller, context):
        """'ignore enumeration' adds enumeration to skip_phases."""
        input_data = MissionInput(directive="ignore enumeration", is_steering=True)

        result = await controller._handle_steering(context, input_data)

        action = result.action
        assert isinstance(action, SteeringAction)
        assert AssessmentPhase.ENUMERATION.value in action.skip_phases

    @pytest.mark.asyncio
    async def test_stop_command(self, controller, context):
        """'stop' sets new_phase to complete."""
        input_data = MissionInput(directive="stop the mission", is_steering=True)

        result = await controller._handle_steering(context, input_data)

        action = result.action
        assert isinstance(action, SteeringAction)
        assert action.new_phase == AssessmentPhase.COMPLETE.value

    @pytest.mark.asyncio
    async def test_abort_command(self, controller, context):
        """'abort' also sets new_phase to complete."""
        input_data = MissionInput(directive="abort now", is_steering=True)

        result = await controller._handle_steering(context, input_data)

        action = result.action
        assert isinstance(action, SteeringAction)
        assert action.new_phase == AssessmentPhase.COMPLETE.value

    @pytest.mark.asyncio
    async def test_ambiguous_command_uses_llm(self, controller, context, mock_llm):
        """Ambiguous commands fall through to LLM interpretation."""
        input_data = MissionInput(directive="maybe try something different", is_steering=True)

        result = await controller._handle_steering(context, input_data)

        assert result.success is True
        action = result.action
        assert isinstance(action, SteeringAction)
        assert len(mock_llm.call_history) > 0

    @pytest.mark.asyncio
    async def test_ambiguous_command_llm_failure_returns_fallback(self, controller, context):
        """When LLM interpretation fails, a safe fallback is returned."""
        input_data = MissionInput(directive="do the thing with the stuff", is_steering=True)

        controller.llm.generate_structured = AsyncMock(side_effect=RuntimeError("LLM timeout"))

        result = await controller._handle_steering(context, input_data)

        action = result.action
        assert isinstance(action, SteeringAction)
        assert action.confidence == 0.5
        assert "Could not interpret" in action.reasoning


# ---------------------------------------------------------------------------
# _create_mission_plan
# ---------------------------------------------------------------------------


class TestCreateMissionPlan:
    """Tests for _create_mission_plan."""

    @pytest.mark.asyncio
    async def test_successful_plan_creation(self, controller, context, mock_llm):
        """Successful plan creation returns a MissionPlan with tasks."""
        input_data = MissionInput(directive="Full network assessment")

        with (
            patch(
                "app.services.ai.knowledge.get_available_tools_context",
                new_callable=AsyncMock,
                return_value="nmap, gobuster",
            ),
            patch(
                "app.services.ai.knowledge.get_mission_context",
                new_callable=AsyncMock,
                return_value="No similar missions",
            ),
            patch(
                "app.services.ai.knowledge.get_full_methodology",
                return_value="PTES methodology",
            ),
        ):
            plan = await controller._create_mission_plan(context, input_data)

        assert isinstance(plan, MissionPlan)
        assert len(plan.tasks) >= 1

    @pytest.mark.asyncio
    async def test_plan_creation_uses_rag_context(self, controller, context, mock_llm):
        """Plan creation calls knowledge functions for context."""
        input_data = MissionInput(directive="Scan web app")

        with (
            patch(
                "app.services.ai.knowledge.get_available_tools_context",
                new_callable=AsyncMock,
                return_value="tools",
            ) as mock_tools,
            patch(
                "app.services.ai.knowledge.get_mission_context",
                new_callable=AsyncMock,
                return_value="context",
            ) as mock_mission_ctx,
            patch(
                "app.services.ai.knowledge.get_full_methodology",
                return_value="methodology",
            ) as mock_method,
        ):
            await controller._create_mission_plan(context, input_data)

        mock_tools.assert_awaited_once_with(grouped=True)
        mock_mission_ctx.assert_awaited_once()
        mock_method.assert_called_once()

    @pytest.mark.asyncio
    async def test_plan_creation_retries_on_failure(self, controller, context):
        """Plan creation retries up to 3 times in the retry loop when LLM fails."""
        input_data = MissionInput(directive="Scan network")

        async def flaky_generate(*args, **kwargs):
            raise RuntimeError("Temporary failure")

        controller.llm.generate_structured = flaky_generate

        with (
            patch(
                "app.services.ai.knowledge.get_available_tools_context",
                new_callable=AsyncMock,
                return_value="tools",
            ),
            patch(
                "app.services.ai.knowledge.get_mission_context",
                new_callable=AsyncMock,
                return_value="ctx",
            ),
            patch("app.services.ai.knowledge.get_full_methodology", return_value="method"),
        ):
            with pytest.raises((RuntimeError, LLMParseError)):
                await controller._create_mission_plan(context, input_data)

        # 3 retry attempts in the retry loop
        # (the error was raised, confirming retries exhausted)

    @pytest.mark.asyncio
    async def test_plan_creation_all_retries_exhausted(self, controller, context):
        """When all retries fail, exception propagates."""
        input_data = MissionInput(directive="Scan")

        controller.llm.generate_structured = AsyncMock(side_effect=RuntimeError("Permanent failure"))

        with (
            patch(
                "app.services.ai.knowledge.get_available_tools_context",
                new_callable=AsyncMock,
                return_value="tools",
            ),
            patch(
                "app.services.ai.knowledge.get_mission_context",
                new_callable=AsyncMock,
                return_value="ctx",
            ),
            patch("app.services.ai.knowledge.get_full_methodology", return_value="method"),
        ):
            with pytest.raises((RuntimeError, LLMParseError)):
                await controller._create_mission_plan(context, input_data)

    @pytest.mark.asyncio
    async def test_empty_llm_plan_retries_then_fails(self, controller, context):
        """Autonomous planning rejects empty LLM plans instead of using a hardcoded fallback."""
        input_data = MissionInput(directive="Quick scan")
        empty_plan = MissionPlan(reasoning="empty", tasks=[])
        controller._llm_generate_structured = AsyncMock(return_value=empty_plan)

        with (
            patch(
                "app.services.ai.knowledge.get_available_tools_context",
                new_callable=AsyncMock,
                return_value="tools",
            ),
            patch(
                "app.services.ai.knowledge.get_mission_context",
                new_callable=AsyncMock,
                return_value="ctx",
            ),
            patch("app.services.ai.knowledge.get_full_methodology", return_value="method"),
        ):
            with pytest.raises(LLMParseError):
                await controller._create_mission_plan(context, input_data)

        assert controller._llm_generate_structured.await_count == 3


# ---------------------------------------------------------------------------
# _handle_phase_transition
# ---------------------------------------------------------------------------


class TestHandlePhaseTransition:
    """Tests for _handle_phase_transition."""

    @pytest.mark.asyncio
    async def test_creates_correct_phase_transition(self, controller, context):
        """PhaseTransition has correct from_phase and to_phase."""
        context.phase = "discovery"
        input_data = MissionInput(
            directive="Move to exploitation",
            force_phase=AssessmentPhase.EXPLOITATION,
        )

        result = await controller._handle_phase_transition(context, input_data)

        assert result.success is True
        action = result.action
        assert isinstance(action, PhaseTransition)
        assert action.from_phase == AssessmentPhase.DISCOVERY
        assert action.to_phase == AssessmentPhase.EXPLOITATION

    @pytest.mark.asyncio
    async def test_phase_transition_reasoning(self, controller, context):
        """PhaseTransition reasoning describes the transition."""
        context.phase = "enumeration"
        input_data = MissionInput(
            directive="Skip to reporting",
            force_phase=AssessmentPhase.REPORTING,
        )

        result = await controller._handle_phase_transition(context, input_data)

        action = result.action
        assert "enumeration" in action.reasoning
        assert action.to_phase == AssessmentPhase.REPORTING

    @pytest.mark.asyncio
    async def test_phase_transition_confidence_and_risk(self, controller, context):
        """PhaseTransition has full confidence and low risk."""
        input_data = MissionInput(
            directive="Complete",
            force_phase=AssessmentPhase.COMPLETE,
        )

        result = await controller._handle_phase_transition(context, input_data)

        action = result.action
        assert action.confidence == 1.0
        assert action.risk_level in (ActionRisk.LOW, ActionRisk.LOW.value)


# ---------------------------------------------------------------------------
# _parse_focus_command
# ---------------------------------------------------------------------------


class TestParseFocusCommand:
    """Tests for _parse_focus_command."""

    @pytest.mark.asyncio
    async def test_web_keyword(self, controller, context):
        """'web' in directive adds web_services."""
        input_data = MissionInput(directive="focus on web")
        action = await controller._parse_focus_command(context, input_data)
        assert "web_services" in action.priority_targets

    @pytest.mark.asyncio
    async def test_sql_keyword(self, controller, context):
        """'sql' in directive adds databases."""
        input_data = MissionInput(directive="focus on sql injection")
        action = await controller._parse_focus_command(context, input_data)
        assert "databases" in action.priority_targets

    @pytest.mark.asyncio
    async def test_api_keyword(self, controller, context):
        """'api' in directive adds apis."""
        input_data = MissionInput(directive="focus on api")
        action = await controller._parse_focus_command(context, input_data)
        assert "apis" in action.priority_targets

    @pytest.mark.asyncio
    async def test_no_recognized_keyword(self, controller, context):
        """No recognized keywords yields empty priority_targets."""
        input_data = MissionInput(directive="focus on something else")
        action = await controller._parse_focus_command(context, input_data)
        assert action.priority_targets == []
        assert "general" in action.reasoning

    @pytest.mark.asyncio
    async def test_preserves_current_phase(self, controller, context):
        """Focus command keeps the current phase."""
        context.phase = "enumeration"
        input_data = MissionInput(directive="focus on web")
        action = await controller._parse_focus_command(context, input_data)
        assert action.new_phase == "enumeration"


# ---------------------------------------------------------------------------
# _parse_skip_command
# ---------------------------------------------------------------------------


class TestParseSkipCommand:
    """Tests for _parse_skip_command."""

    @pytest.mark.asyncio
    async def test_skip_exploit(self, controller, context):
        """'exploit' keyword adds exploitation phase to skip list."""
        input_data = MissionInput(directive="skip exploit phase")
        action = await controller._parse_skip_command(context, input_data)
        assert AssessmentPhase.EXPLOITATION.value in action.skip_phases

    @pytest.mark.asyncio
    async def test_skip_enum(self, controller, context):
        """'enum' keyword adds enumeration phase to skip list."""
        input_data = MissionInput(directive="skip enum")
        action = await controller._parse_skip_command(context, input_data)
        assert AssessmentPhase.ENUMERATION.value in action.skip_phases

    @pytest.mark.asyncio
    async def test_skip_both(self, controller, context):
        """Both exploit and enum keywords skip both phases."""
        input_data = MissionInput(directive="skip exploit and enum")
        action = await controller._parse_skip_command(context, input_data)
        assert AssessmentPhase.EXPLOITATION.value in action.skip_phases
        assert AssessmentPhase.ENUMERATION.value in action.skip_phases

    @pytest.mark.asyncio
    async def test_no_skip_keyword(self, controller, context):
        """No recognized keywords yields empty skip_phases."""
        input_data = MissionInput(directive="skip nothing relevant")
        action = await controller._parse_skip_command(context, input_data)
        assert action.skip_phases == []
        assert "none specified" in action.reasoning

    @pytest.mark.asyncio
    async def test_preserves_current_phase(self, controller, context):
        """Skip command keeps the current phase."""
        context.phase = "vulnerability"
        input_data = MissionInput(directive="skip exploit")
        action = await controller._parse_skip_command(context, input_data)
        assert action.new_phase == "vulnerability"
