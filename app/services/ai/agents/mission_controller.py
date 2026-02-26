"""
MissionController Agent - Orchestrates the assessment workflow.

Responsible for:
- Receiving high-level user directives
- Breaking down missions into actionable tasks
- Coordinating between other agents
- Handling steering commands
- Managing phase transitions
"""

import logging
from enum import Enum
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from app.core.enums import AssessmentPhase
from app.services.ai.agents.base import (
    ActionRisk,
    Agent,
    AgentAction,
    AgentContext,
    AgentResult,
    AgentRole,
    SteeringAction,
)
from app.services.ai.prompts import (
    MISSION_CONTROLLER_SYSTEM_PROMPT,
    MISSION_PLAN_PROMPT,
)

logger = logging.getLogger("spectra.ai.agents.mission")


# --- Enums ---


class MissionType(str, Enum):
    """Types of missions the controller can handle."""

    FULL_ASSESSMENT = "full_assessment"
    RECON_ONLY = "recon_only"
    VULN_SCAN = "vuln_scan"
    EXPLOIT = "exploit"
    CUSTOM = "custom"


# --- Input/Output Models ---


class MissionInput(BaseModel):
    """Input for the MissionController."""

    directive: str = Field(..., description="User's high-level directive")
    is_steering: bool = Field(
        False, description="Is this a mid-mission steering command?"
    )
    force_phase: AssessmentPhase | None = Field(
        None, description="Force transition to phase"
    )


class Task(BaseModel):
    """A single task in the mission plan."""

    task_id: str = Field(..., description="Unique task identifier")
    description: str = Field(..., description="What the task does")
    agent_type: str = Field(..., description="Which agent handles this task")
    phase: AssessmentPhase = Field(..., description="Assessment phase")
    priority: int = Field(1, ge=1, le=5, description="Priority 1-5 (1 is highest)")
    dependencies: list[str] = Field(
        default_factory=list, description="Task IDs this depends on"
    )
    parameters: dict[str, Any] = Field(default_factory=dict)


class MissionPlan(AgentAction):
    """Output from the MissionController - a plan of tasks."""

    action_type: str = Field(default="mission_plan", description="Action type")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    risk_level: ActionRisk = Field(default=ActionRisk.LOW)
    reasoning: str = Field(default="Mission plan generated")

    mission_type: MissionType = Field(default=MissionType.FULL_ASSESSMENT)
    tasks: list[Task] = Field(default_factory=list)
    current_phase: AssessmentPhase = Field(default=AssessmentPhase.SCOPE)
    estimated_duration_minutes: int = Field(default=30)
    requires_approval: bool = Field(default=False)
    approval_reason: str | None = Field(default=None)


class PhaseTransition(AgentAction):
    """Transition to a new assessment phase."""

    action_type: str = "phase_transition"
    from_phase: AssessmentPhase
    to_phase: AssessmentPhase
    summary: str = Field(..., description="Summary of completed phase")
    findings_count: int = Field(0)


# --- MissionController Implementation ---


class MissionController(
    Agent[MissionInput, MissionPlan | PhaseTransition | SteeringAction]
):
    """
    The "Manager" agent that orchestrates the assessment workflow.
    """

    role: ClassVar[AgentRole] = AgentRole.MISSION_CONTROLLER
    name: ClassVar[str] = "MissionController"

    def __init__(self, llm: Any):
        super().__init__(llm)
        # Import here to avoid circular dependency
        from app.services.ai.consensus import VotingSystem

        self.consensus = VotingSystem(llm)

    async def execute(
        self,
        context: AgentContext,
        input_data: MissionInput,
    ) -> AgentResult:
        """Process directive and create mission plan or handle steering."""
        try:
            if input_data.is_steering:
                return await self._handle_steering(context, input_data)

            if input_data.force_phase:
                return await self._handle_phase_transition(context, input_data)

            # Parse directive and create mission plan
            plan = await self._create_mission_plan(context, input_data)

            return AgentResult(
                success=True,
                action=plan,
            )

        except Exception as e:
            logger.error("MissionController failed: %s", e)
            return AgentResult(
                success=False,
                error=str(e),
            )

    async def _create_mission_plan(
        self,
        context: AgentContext,
        input_data: MissionInput,
    ) -> MissionPlan:
        """Create a mission plan from the directive using MAKER Consensus and RAG."""
        from app.services.ai.knowledge import (
            get_available_tools_context,
            get_full_methodology,
            get_mission_context,
        )

        # Get available tools to inform planning using centralized service
        tools_context = await get_available_tools_context(grouped=True)

        # Get RAG context for similar past missions using centralized service
        rag_context = await get_mission_context(input_data.directive, context.target)

        # Get full methodology using centralized service
        methodology_summary = get_full_methodology()

        # Get learned context from persistent memory
        try:
            from app.services.ai.memory import get_memory
            memory = get_memory()
            memory_context = memory.get_context_for_prompt()
            if memory_context:
                rag_context += f"\n\n--- Learned from Past Missions ---\n{memory_context}"
            stats = memory.get_stats()
            if stats["tool_lessons"] > 0 or stats["exploit_lessons"] > 0:
                rag_context += f"\n(Memory: {stats['tool_lessons']} tool lessons, {stats['exploit_lessons']} exploit patterns, {stats['target_profiles']} OS profiles)"
        except Exception:
            pass

        prompt = MISSION_PLAN_PROMPT.format(
            directive=input_data.directive,
            target=context.target or "Not specified",
            methodology=methodology_summary,
            tools_context=tools_context,
            rag_context=rag_context,
        )

        system_prompt = MISSION_CONTROLLER_SYSTEM_PROMPT.format(
            description=self.description,
            session_id=context.session_id or context.mission_id,
            target=context.target or "Not specified",
            phase=context.phase,
            mission=context.mission or "Standard security assessment",
        )

        # Generate plan using LLM
        response = await self.llm.generate_structured(
            prompt=prompt,
            response_model=MissionPlan,
            system_prompt=system_prompt,
            temperature=self._get_temperature(input_data),
        )

        system_prompt = (
            self._build_system_prompt(context)
            + """
You are acting as a Lead Security Architect following the MAKER framework.
Your plan must be:
- Methodologically sound (following PTES)
- Safe (no unauthorized exploitation)
- Comprehensive (cover all relevant phases)
- Practical (use only available tools)
"""
        )

        try:
            # Retry logic for plan generation
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    plan = await self.llm.generate_structured(
                        prompt=prompt,
                        response_model=MissionPlan,
                        system_prompt=system_prompt,
                        temperature=0.4,
                        max_tokens=4096,
                    )
                    return plan
                except Exception as e:
                    logger.warning(
                        "Plan generation attempt %d failed: %s", attempt + 1, e
                    )
                    if attempt == max_retries - 1:
                        raise e
                    # Slightly adjust prompt or temperature on retry if needed
                    # For now, just retry
        except Exception as e:
            logger.error("Plan generation failed after %d attempts: %s", max_retries, e)
            raise e

    async def _handle_steering(
        self,
        context: AgentContext,
        input_data: MissionInput,
    ) -> AgentResult:
        """Handle a steering command to change mission direction."""
        directive_lower = input_data.directive.lower()

        # Parse steering intent
        if "focus" in directive_lower or "prioritize" in directive_lower:
            # User wants to focus on something specific
            action = await self._parse_focus_command(context, input_data)
        elif "skip" in directive_lower or "ignore" in directive_lower:
            # User wants to skip something
            action = await self._parse_skip_command(context, input_data)
        elif "stop" in directive_lower or "abort" in directive_lower:
            # User wants to stop
            action = SteeringAction(
                confidence=1.0,
                risk_level=ActionRisk.LOW,
                reasoning="User requested mission abort",
                new_phase=AssessmentPhase.COMPLETE.value,
            )
        else:
            # Use LLM to interpret the steering command
            action = await self._interpret_steering(context, input_data)

        return AgentResult(
            success=True,
            action=action,
        )

    async def _handle_phase_transition(
        self,
        context: AgentContext,
        input_data: MissionInput,
    ) -> AgentResult:
        """Handle a forced phase transition."""
        action = PhaseTransition(
            confidence=1.0,
            risk_level=ActionRisk.LOW,
            reasoning=f"Phase transition requested: {context.phase} -> {input_data.force_phase}",
            from_phase=AssessmentPhase(context.phase),
            to_phase=input_data.force_phase,  # type: ignore
            summary=f"Transitioning from {context.phase}",
        )

        return AgentResult(
            success=True,
            action=action,
        )

    async def _parse_focus_command(
        self,
        context: AgentContext,
        input_data: MissionInput,
    ) -> SteeringAction:
        """Parse a focus/prioritize steering command."""
        directive = input_data.directive.lower()

        priority_targets = []
        if "web" in directive:
            priority_targets.append("web_services")
        if "database" in directive or "sql" in directive:
            priority_targets.append("databases")
        if "api" in directive:
            priority_targets.append("apis")

        return SteeringAction(
            confidence=0.8,
            risk_level=ActionRisk.LOW,
            reasoning=f"Focusing on: {', '.join(priority_targets) or 'general'}",
            new_phase=context.phase,
            priority_targets=priority_targets,
        )

    async def _parse_skip_command(
        self,
        context: AgentContext,
        input_data: MissionInput,
    ) -> SteeringAction:
        """Parse a skip/ignore steering command."""
        directive = input_data.directive.lower()

        skip_phases = []
        if "exploit" in directive:
            skip_phases.append(AssessmentPhase.EXPLOITATION.value)
        if "enum" in directive:
            skip_phases.append(AssessmentPhase.ENUMERATION.value)

        return SteeringAction(
            confidence=0.8,
            risk_level=ActionRisk.LOW,
            reasoning=f"Skipping phases: {', '.join(skip_phases) or 'none specified'}",
            new_phase=context.phase,
            skip_phases=skip_phases,
        )

    async def _interpret_steering(
        self,
        context: AgentContext,
        input_data: MissionInput,
    ) -> SteeringAction:
        """Use LLM to interpret ambiguous steering commands."""
        prompt = f"""Interpret this steering command for an ongoing security assessment.

Command: "{input_data.directive}"
Current Phase: {context.phase}
Mission: {context.mission or "Standard assessment"}

Determine:
1. What changes should be made to the assessment direction
2. Any phases to skip or prioritize
3. Any targets to focus on or exclude"""

        try:
            return await self.llm.generate_structured(
                prompt=prompt,
                response_model=SteeringAction,
                system_prompt=self._build_system_prompt(context),
                temperature=0.3,
            )
        except Exception as e:
            logger.warning("Steering interpretation failed: %s", e)
            return SteeringAction(
                confidence=0.5,
                risk_level=ActionRisk.LOW,
                reasoning=f"Could not interpret steering command: {input_data.directive}",
                new_phase=context.phase,
            )
