"""
MissionController Agent - Orchestrates the assessment workflow.

Responsible for:
- Receiving high-level user directives
- Breaking down missions into actionable tasks
- Coordinating between other agents
- Handling steering commands
- Managing phase transitions
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, Field

from spectra_ai.errors import AgentError, LLMParseError, LLMTimeoutError
from spectra_ai.prompts import (
    MISSION_PLAN_PROMPT,
)
from spectra_ai.sanitizer import sanitize_for_prompt
from spectra_platform.mission.core.enums import AssessmentPhase
from spectra_platform.services.ai.agents.base import (
    ActionRisk,
    Agent,
    AgentAction,
    AgentContext,
    AgentResult,
    AgentRole,
    SteeringAction,
)
from spectra_platform.services.ai.agents.registry import register_agent

if TYPE_CHECKING:
    from spectra_ai.llm import LLMClient

logger = logging.getLogger(__name__)


# --- Enums ---


class MissionType(StrEnum):
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
    requirements: str | None = Field(None, description="Additional mission constraints")
    is_steering: bool = Field(False, description="Is this a mid-mission steering command?")
    force_phase: AssessmentPhase | None = Field(None, description="Force transition to phase")


class Task(BaseModel):
    """A single task in the mission plan."""

    task_id: str = Field(..., description="Unique task identifier")
    description: str = Field(..., description="What the task does")
    agent_type: str = Field(..., description="Which agent handles this task")
    phase: AssessmentPhase = Field(..., description="Assessment phase")
    priority: int = Field(1, ge=1, le=5, description="Priority 1-5 (1 is highest)")
    dependencies: list[str] = Field(default_factory=list, description="Task IDs this depends on")
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


@register_agent
class MissionController(Agent[MissionInput, MissionPlan | PhaseTransition | SteeringAction]):
    """
    The "Manager" agent that orchestrates the assessment workflow.
    """

    role: ClassVar[AgentRole] = AgentRole.MISSION_CONTROLLER
    name: ClassVar[str] = "MissionController"
    enable_reflection: ClassVar[bool] = True
    reflection_threshold: ClassVar[float] = 0.7

    def __init__(self, llm: LLMClient):
        super().__init__(llm)
        # Import here to avoid circular dependency
        from spectra_platform.services.ai.consensus import VotingSystem

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

            # Pre-flight safety risk assessment via SafetyAgent sub-agent
            safety_metadata: dict[str, Any] = {}
            try:
                from spectra_platform.services.ai.agents.safety import SafetyInput

                logger.info("Spawning SafetyAgent for pre-flight risk assessment")
                safety_input = SafetyInput(
                    command=f"assess_scope {context.target or 'unknown'}",
                    tool_id="mission_preflight",
                    target=context.target or "unknown",
                    args={"directive": input_data.directive},
                )
                safety_result = await self.spawn_sub_agent(AgentRole.SAFETY_SUPERVISOR, context, safety_input)
                if safety_result.success and safety_result.action:
                    safety_action = safety_result.action
                    safety_metadata["preflight_allowed"] = getattr(safety_action, "allowed", True)
                    safety_metadata["preflight_risk"] = getattr(safety_action, "risk_level", "low")
                    safety_metadata["preflight_reason"] = getattr(safety_action, "reason", "")
                    logger.info(
                        "Pre-flight safety check: allowed=%s risk=%s",
                        safety_metadata["preflight_allowed"],
                        safety_metadata["preflight_risk"],
                    )
            except (OSError, RuntimeError, ValueError):
                logger.exception("Pre-flight safety check failed (non-fatal)")

            # Parse directive and create mission plan
            plan = await self._create_mission_plan(context, input_data)

            result = AgentResult(
                success=True,
                action=plan,
            )
            if safety_metadata:
                result.metadata.update(safety_metadata)
            return result

        except AgentError:
            raise
        except TimeoutError as e:
            raise LLMTimeoutError(agent=self.name, timeout_seconds=0) from e
        except (OSError, RuntimeError, ValueError) as e:
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
        from spectra_platform.services.ai.knowledge import (
            get_available_tools_context,
            get_full_methodology,
            get_mission_context,
        )

        # Get available tools to inform planning using centralized service
        tools_context = await get_available_tools_context(grouped=True)

        # Get RAG context for similar past missions using centralized service
        rag_context = await get_mission_context(
            input_data.directive,
            context.target,
            user_id=context.user_id,
            exclude_session_id=context.mission_id,
        )

        # Get full methodology using centralized service
        methodology_summary = get_full_methodology()

        # Get learned context from persistent memory
        memory_context = ""
        try:
            from spectra_platform.services.ai.memory import get_memory

            memory = get_memory(context.user_id)
            memory_context = memory.get_context_for_prompt()
            stats = memory.get_stats()
            if stats["tool_lessons"] > 0 or stats["exploit_lessons"] > 0:
                memory_context += f"\n(Memory: {stats['tool_lessons']} tool lessons, {stats['exploit_lessons']} exploit patterns, {stats['target_profiles']} OS profiles)"
        except (OSError, RuntimeError, ValueError) as e:
            logger.debug("Memory context fetch failed: %s", e)

        # Fetch lessons learned from previous debriefs
        lessons_context = ""
        try:
            from spectra_platform.services.ai.memory import get_memory as _get_memory

            _mem = _get_memory(context.user_id)
            debrief_lessons = [lesson for lesson in _mem.tool_lessons if lesson.tool_id == "debrief" and lesson.notes]
            if debrief_lessons:
                lessons_context = "\n**Lessons from Previous Missions:**\n" + "\n".join(
                    f"- {lesson.notes}" for lesson in debrief_lessons[-5:]
                )
        except (OSError, RuntimeError, ValueError):
            logger.debug("Could not fetch debrief lessons from memory", exc_info=True)

        from spectra_platform.services.ai.context import ContextManager, ContextSection, Priority

        sanitized_directive = sanitize_for_prompt(input_data.directive, field_name="directive")
        sanitized_requirements = sanitize_for_prompt(input_data.requirements or "None", field_name="requirements")

        plan_prompt_text = MISSION_PLAN_PROMPT.format(
            directive=sanitized_directive,
            target=context.target or "Not specified",
            requirements=sanitized_requirements,
            methodology="",
            tools_context="",
            rag_context="",
        )

        ctx = ContextManager(max_context_tokens=6000)
        prompt = ctx.build(
            [
                ContextSection("task", plan_prompt_text, Priority.CRITICAL),
                ContextSection("tools", tools_context, Priority.HIGH, max_tokens=800),
                ContextSection("methodology", methodology_summary, Priority.LOW, max_tokens=400),
                ContextSection("memory", memory_context, Priority.MEDIUM, max_tokens=500),
                ContextSection("lessons", lessons_context, Priority.MEDIUM, max_tokens=400),
                ContextSection("rag", rag_context, Priority.LOW, max_tokens=500),
            ]
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

IMPORTANT OPERATIONAL GUIDELINES:
- Prefer exploit-based attacks (CVEs, known backdoors, default credentials) over brute force
- If brute force is necessary, use short targeted wordlists (top 20 passwords) not exhaustive lists
- Use the tool's built-in default credential checks first
- Focus on high-value, high-probability attack vectors
- Parallel tool execution is preferred when targets/services are independent
"""
        )

        try:
            # Retry logic for plan generation
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    plan = await self._llm_generate_structured(
                        prompt=prompt,
                        response_model=MissionPlan,
                        system_prompt=system_prompt,
                        temperature=0.4,
                        max_tokens=4096,
                    )
                    plan = self._enforce_directive_constraints(plan, input_data)
                    if not plan.tasks:
                        raise ValueError("LLM returned an empty mission plan")
                    return plan
                except (OSError, RuntimeError, ValueError, TimeoutError) as e:
                    logger.warning("Plan generation attempt %d failed: %s", attempt + 1, e)
                    if attempt == max_retries - 1:
                        raise LLMParseError(agent=self.name, raw_response=str(e)) from e
                    # Slightly adjust prompt or temperature on retry if needed
                    # For now, just retry
            raise LLMParseError(agent=self.name, raw_response="Plan generation exhausted retries")
        except AgentError:
            raise
        except (OSError, RuntimeError, ValueError, TimeoutError) as e:
            logger.error("Plan generation failed after %d attempts: %s", max_retries, e)
            raise

    def _enforce_directive_constraints(self, plan: MissionPlan, input_data: MissionInput) -> MissionPlan:
        """Apply deterministic safety/runtime constraints after LLM planning."""
        constraints = f"{input_data.directive}\n{input_data.requirements or ''}".lower()
        quick_markers = ("quick", "validation", "smoke", "basic", "short")
        safe_markers = ("safe", "recon", "reconnaissance", "non-destructive", "avoid destructive")

        if any(marker in constraints for marker in safe_markers):
            blocked_phases = {AssessmentPhase.EXPLOITATION, AssessmentPhase.POST_EXPLOITATION}
            allowed_task_ids = {
                task.task_id for task in plan.tasks if task.phase not in blocked_phases and task.agent_type != "exploit_crafter"
            }
            plan.tasks = [
                task.model_copy(update={"dependencies": [dep for dep in task.dependencies if dep in allowed_task_ids]})
                for task in plan.tasks
                if task.task_id in allowed_task_ids
            ]
            if plan.mission_type == MissionType.EXPLOIT:
                plan.mission_type = MissionType.VULN_SCAN

        if any(marker in constraints for marker in quick_markers):
            plan.reasoning = f"{plan.reasoning} Quick validation requested; preserving LLM-authored tasks."
            plan.estimated_duration_minutes = min(plan.estimated_duration_minutes, 15)

        return plan

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
        directive_safe = sanitize_for_prompt(input_data.directive, field_name="steering_directive")
        mission_safe = sanitize_for_prompt(
            context.mission or "Standard assessment",
            max_length=2000,
            field_name="mission",
        )
        prompt = f"""Interpret this steering command for an ongoing security assessment.

Command: "{directive_safe}"
Current Phase: {context.phase}
Mission: {mission_safe}

Determine:
1. What changes should be made to the assessment direction
2. Any phases to skip or prioritize
3. Any targets to focus on or exclude"""

        try:
            return await self._llm_generate_structured(
                prompt=prompt,
                response_model=SteeringAction,
                system_prompt=self._build_system_prompt(context),
                temperature=0.3,
            )
        except (OSError, RuntimeError, ValueError, TimeoutError) as e:
            logger.warning("Steering interpretation failed: %s", e)
            return SteeringAction(
                confidence=0.5,
                risk_level=ActionRisk.LOW,
                reasoning=f"Could not interpret steering command: {directive_safe}",
                new_phase=context.phase,
            )
