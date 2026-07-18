from __future__ import annotations

import asyncio
import json as _json
import logging
import random
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Generic, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field

from spectra_ai_core.cost_tracker import CostTracker
from spectra_ai_core.llm import LLMClient, _extract_json_block
from spectra_ai_core.prompts import BASE_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


# --- Enums ---


class AgentRole(StrEnum):
    """Defines the role/responsibility of an agent."""

    SCOPE = "scope"  # Parses input to define boundaries
    TOOL_SELECTOR = "tool_selector"  # Chooses the right tool
    PARAMETER_TUNER = "parameter_tuner"  # Adjusts tool parameters
    PARSER = "parser"  # Parses tool output
    MISSION_CONTROLLER = "mission_controller"  # Orchestrates workflow
    SAFETY_SUPERVISOR = "safety_supervisor"  # Blocks dangerous actions
    EXPLOIT_CRAFTER = "exploit_crafter"  # Crafts exploits
    EXPLOIT_VERIFIER = "exploit_verifier"  # Verifies exploit success
    POC_DEVELOPER = "poc_developer"  # Writes custom exploit scripts
    POST_EXPLOITATION = "post_exploitation"  # Plans post-exploitation activities
    VECTOR_GENERATOR = "vector_generator"  # Generates attack vectors
    DEBRIEF = "debrief"  # Post-mission analysis and lessons learned
    REPORTER = "reporter"  # Generates assessment reports
    RECON_INTEL = "recon_intel"  # OSINT / web intelligence gathering


class ActionRisk(StrEnum):
    """Risk level of an agent action."""

    LOW = "low"  # Safe to execute automatically
    MEDIUM = "medium"  # Requires logging
    HIGH = "high"  # Requires voting/consensus
    CRITICAL = "critical"  # Requires human approval


# --- Context Models ---


class AgentContext(BaseModel):
    """Context passed to agents for decision making."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    mission_id: str = Field(..., description="Current mission ID")
    session_id: str | None = None
    user_id: str | None = None
    user_role: str | None = None
    plan_features: dict[str, Any] = Field(default_factory=dict, description="Server-derived plan features")
    tenant_quotas: dict[str, Any] = Field(default_factory=dict, description="Server-derived tenant quota snapshot")
    target: str | None = None
    mission: str | None = None
    phase: str = "discovery"

    # State from previous actions
    previous_findings: list[dict[str, Any]] = Field(default_factory=list)
    previous_actions: list[dict[str, Any]] = Field(default_factory=list)
    available_tools: list[str] = Field(default_factory=list)

    # Constraints
    stealth_mode: bool = False
    max_concurrency: Annotated[int, Field(ge=1, le=32)] = 3

    # Extra context from blackboard/intelligence
    extra_context: str = ""

    # Cost tracking (excluded from serialization)
    cost_tracker: CostTracker | None = None


# --- Action Models ---


class AgentAction(BaseModel):
    """Base class for agent actions/decisions."""

    action_type: str = Field(..., description="Type of action to take")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score")
    risk_level: ActionRisk = Field(ActionRisk.LOW, description="Risk assessment")
    reasoning: str = Field(..., description="Explanation for the decision")

    model_config = ConfigDict(use_enum_values=True)


class ToolAction(AgentAction):
    """Action to run a security tool."""

    action_type: str = "run_tool"
    tool_name: str = Field(..., description="Name of tool to run")
    tool_args: dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    target: str = Field(..., description="Target for the tool")
    estimated_duration: int = Field(60, description="Estimated duration in seconds")


class ParallelToolAction(AgentAction):
    """Action to run multiple tools in parallel."""

    action_type: str = "run_tools_parallel"
    tools: list[ToolAction] = Field(..., description="Tools to run concurrently")
    max_concurrency: Annotated[int, Field(ge=1, le=32, description="Max parallel tool executions")] = 3


class SteeringAction(AgentAction):
    """Action to change assessment direction."""

    action_type: str = "steer"
    new_phase: str = Field(..., description="Phase to transition to")
    priority_targets: list[str] = Field(default_factory=list)
    skip_phases: list[str] = Field(default_factory=list)


class ApprovalRequest(AgentAction):
    """Request for human approval."""

    action_type: str = "request_approval"
    pending_action: dict[str, Any] = Field(..., description="Action awaiting approval")
    timeout_seconds: int = Field(300, description="Time to wait for approval")
    default_on_timeout: bool = Field(False, description="Default action if timeout")


# --- Result Types ---


@dataclass
class AgentResult:
    """Result from an agent execution."""

    success: bool
    action: AgentAction | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# --- Base Agent ---

# Maps AgentRole → task_type string used by TensorZeroRouter for tier routing
ROLE_TASK_MAP: dict[AgentRole, str] = {
    AgentRole.SCOPE: "scope",
    AgentRole.TOOL_SELECTOR: "tool_selection",
    AgentRole.PARAMETER_TUNER: "tool_selection",
    AgentRole.PARSER: "parsing",
    AgentRole.MISSION_CONTROLLER: "planning",
    AgentRole.SAFETY_SUPERVISOR: "safety_check",
    AgentRole.EXPLOIT_CRAFTER: "exploit_crafting",
    AgentRole.EXPLOIT_VERIFIER: "exploit_crafting",
    AgentRole.POC_DEVELOPER: "poc_generation",
    AgentRole.POST_EXPLOITATION: "post_exploitation",
    AgentRole.VECTOR_GENERATOR: "vector_generation",
    AgentRole.DEBRIEF: "reporting",
    AgentRole.REPORTER: "reporting",
    AgentRole.RECON_INTEL: "planning",
}


InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=AgentAction)


class Agent(ABC, Generic[InputT, OutputT]):
    """Base class for all MAKER agents."""

    role: ClassVar[AgentRole]
    name: ClassVar[str] = "BaseAgent"
    description: ClassVar[str] = "Base agent class"

    # Reflection settings — override in creative agents
    enable_reflection: ClassVar[bool] = False
    reflection_threshold: ClassVar[float] = 0.7

    # Default system prompt template
    system_prompt_template: ClassVar[str] = BASE_SYSTEM_PROMPT

    def __init__(self, llm: LLMClient):
        """
        Initialize the agent with an LLM client.

        Args:
            llm: The LLM client to use for generation.
        """
        self.llm = llm
        self._cost_tracker: CostTracker | None = None
        self._last_inference_id: str = ""

    @property
    def _task_type(self) -> str | None:
        """Get the task_type string for this agent's role (used for tier routing)."""
        return ROLE_TASK_MAP.get(self.role)

    async def _llm_generate(self, **kwargs: Any) -> Any:
        """Call self.llm.generate() with automatic task_type injection and cost tracking."""
        kwargs.setdefault("task_type", self._task_type)
        start = time.monotonic()
        response = await self.llm.generate(**kwargs)
        latency = (time.monotonic() - start) * 1000

        # Capture inference_id for feedback
        if hasattr(response, "raw") and isinstance(response.raw, dict):
            self._last_inference_id = response.raw.get("inference_id", "")

        if self._cost_tracker:
            self._cost_tracker.record(
                agent_name=self.name,
                agent_role=self.role.value,
                model=response.model,
                usage=response.usage,
                latency_ms=latency,
            )
        return response

    async def _llm_generate_structured(self, **kwargs: Any) -> Any:
        """Call self.llm.generate_structured() with automatic task_type injection."""
        kwargs.setdefault("task_type", self._task_type)
        return await self.llm.generate_structured(**kwargs)

    def _build_system_prompt(self, context: AgentContext) -> str:
        """Build the system prompt from context."""
        return self.system_prompt_template.format(
            name=self.name,
            description=self.description,
            session_id=context.session_id or context.mission_id,
            target=context.target or "Not specified",
            phase=context.phase,
            mission=context.mission or "Standard security assessment",
        )

    async def _llm_stream(self, **kwargs: Any) -> AsyncIterator[str]:
        """Stream LLM tokens with automatic task_type injection and UI broadcast."""
        kwargs.setdefault("task_type", self._task_type)
        collected: list[str] = []
        async for chunk in self.llm.stream(**kwargs):
            collected.append(chunk)
            self.broadcast_thought(chunk)
            yield chunk

    async def _reflect(self, context: AgentContext, action: OutputT) -> tuple[float, str]:
        """Self-critique the output. Returns (quality_score, feedback)."""
        prompt = (
            f"You are reviewing the output of {self.name} ({self.description}).\n\n"
            f"The agent was working on: {context.mission or 'security assessment'}\n"
            f"Phase: {context.phase}\n"
            f"Target: {context.target or 'unspecified'}\n\n"
            f"Agent's output:\n"
            f"Action type: {action.action_type}\n"
            f"Confidence: {action.confidence}\n"
            f"Reasoning: {action.reasoning}\n\n"
            "Rate the quality of this output on a scale of 0.0 to 1.0 and provide brief feedback.\n"
            'Respond in JSON: {"quality": 0.85, "feedback": "..."}'
        )
        try:
            response = await self._llm_generate(
                prompt=prompt,
                system_prompt="You are a quality reviewer for AI agent outputs. Be critical but fair.",
                temperature=0.1,
                max_tokens=256,
            )
            content = response.content
            data = _json.loads(_extract_json_block(content))
            return float(data.get("quality", 0.8)), str(data.get("feedback", ""))
        except (OSError, RuntimeError, ValueError, TimeoutError) as e:
            logger.debug("Reflection failed: %s", e)
            return 0.8, ""

    async def execute_with_reflection(
        self,
        context: AgentContext,
        input_data: InputT,
        max_iterations: int = 2,
    ) -> AgentResult:
        """Execute with optional reflection/self-critique loop.

        If enable_reflection is True and output quality is below threshold,
        retry with the critique as additional context.
        """
        if not self.enable_reflection:
            return await self.execute(context, input_data)

        best_result: AgentResult | None = None
        best_quality = 0.0

        for iteration in range(max_iterations):
            result = await self.execute(context, input_data)

            if not result.success or not result.action:
                return result

            # ``execute`` is the subclass contract for this agent's OutputT;
            # AgentResult stores the common base type for cross-agent callers.
            quality, feedback = await self._reflect(context, cast(OutputT, result.action))

            self.broadcast_thought(f"[Reflection #{iteration + 1}] Quality: {quality:.2f} — {feedback}")

            if quality > best_quality:
                best_result = result
                best_quality = quality

            if quality >= self.reflection_threshold:
                return result

            context.extra_context += (
                f"\n\n[Self-critique feedback]: {feedback}\nPlease improve your output based on this feedback."
            )

        return best_result or result  # type: ignore[possibly-undefined]

    def _get_temperature(self, input_data: InputT, attempt: int = 1) -> float:
        """
        Determine the temperature for LLM generation based on task complexity.

        On retries, increase temperature by 0.1 per attempt (capped at 1.0).
        Can be overridden by subclasses.
        """
        # Default logic:
        # - Scope/Safety/Parser -> Low (Precision)
        # - Exploit/Mission -> High (Creativity)

        if self.role in (
            AgentRole.SCOPE,
            AgentRole.PARSER,
            AgentRole.SAFETY_SUPERVISOR,
        ):
            base = 0.1
        elif self.role in (
            AgentRole.EXPLOIT_CRAFTER,
            AgentRole.POC_DEVELOPER,
        ):
            base = 0.7
        elif self.role in (
            AgentRole.MISSION_CONTROLLER,
            AgentRole.POST_EXPLOITATION,
            AgentRole.VECTOR_GENERATOR,
            AgentRole.DEBRIEF,
        ):
            base = 0.4
        else:
            base = 0.3

        # Adaptive: increase temperature on retries
        adjusted = base + 0.1 * (attempt - 1)
        return min(adjusted, 1.0)

    @abstractmethod
    async def execute(
        self,
        context: AgentContext,
        input_data: InputT,
    ) -> AgentResult:
        """
        Execute the agent's primary function.

        Args:
            context: Current session/mission context.
            input_data: Agent-specific input data.

        Returns:
            AgentResult with the action or error.
        """
        ...

    async def spawn_sub_agent(
        self,
        role: AgentRole,
        context: AgentContext,
        input_data: BaseModel,
        *,
        depth: int = 0,
        max_depth: int = 3,
    ) -> AgentResult:
        """Spawn a sub-agent to handle a subtask.

        Args:
            role: The role of the sub-agent to spawn.
            context: Context to pass to the sub-agent.
            input_data: Input for the sub-agent's execute method.
            depth: Current nesting depth.
            max_depth: Maximum allowed nesting depth.

        Returns:
            AgentResult from the sub-agent.

        Raises:
            RecursionError: If depth exceeds max_depth.
        """
        if depth >= max_depth:
            raise RecursionError(f"Sub-agent spawn depth {depth} exceeds max_depth {max_depth}")

        from spectra_ai_core.agents.registry import get_agent_registry

        registry = get_agent_registry()
        sub_agent = registry.create(role, self.llm)

        self.broadcast_thought(f"Spawning sub-agent {sub_agent.name} (role={role}, depth={depth + 1})")

        result = await sub_agent.execute(context, input_data)

        # Track parent-child relationship in metadata
        result.metadata["parent_agent"] = self.name
        result.metadata["parent_role"] = self.role.value
        result.metadata["spawn_depth"] = depth + 1

        return result

    async def validate_action(self, action: OutputT) -> tuple[bool, str | None]:
        """
        Validate an action before execution.

        Can be overridden by subclasses for custom validation.

        Args:
            action: The action to validate.

        Returns:
            Tuple of (is_valid, error_message).
        """
        # Default validation: check confidence threshold
        if action.confidence < 0.3:
            return False, f"Confidence too low: {action.confidence}"
        return True, None

    def requires_approval(self, action: OutputT) -> bool:
        """Check if an action requires human approval.

        - If ``REQUIRE_APPROVAL`` is set in environment (operator kill-switch), high/critical
          actions always require approval.
        - Otherwise, only when the mission was started with ``requires_approval=True``.
        """
        from spectra_common.config import settings

        if action.risk_level not in (ActionRisk.HIGH, ActionRisk.CRITICAL):
            return False
        if settings.REQUIRE_APPROVAL:
            return True
        return bool(getattr(self, "_mission_requires_approval", False))

    def requires_consensus(self, action: OutputT) -> bool:
        """Check if an action requires consensus voting."""
        return action.risk_level == ActionRisk.HIGH

    def broadcast_thought(self, content: str) -> None:
        """
        Broadcast a thought/reasoning step to the UI.

        This enables the 'Stream of Consciousness' display.
        """
        from spectra_infra.events import EventType, events

        events.emit_sync(
            EventType.AGENT_THOUGHT,
            source=self.name,
            content=content,
            role=self.role.value,
        )

    async def _execute_with_retry(
        self,
        func: Callable[..., Any],
        *args: Any,
        max_retries: int = 2,
        backoff_factor: float = 1.5,
        **kwargs: Any,
    ) -> Any:
        """Execute a coroutine with retry and exponential backoff.

        Args:
            func: Async callable to execute.
            *args: Positional arguments for func.
            max_retries: Maximum number of retries after initial failure.
            backoff_factor: Multiplier for exponential backoff.
            **kwargs: Keyword arguments for func.

        Returns:
            The result of the successful call.

        Raises:
            The last exception if all retries are exhausted.
        """
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
                last_error = exc
                if attempt < max_retries:
                    delay = backoff_factor**attempt + random.uniform(0, 1)
                    logger.warning(
                        "%s retry %d/%d after error: %s (backoff %.1fs)",
                        self.name,
                        attempt + 1,
                        max_retries,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
        raise last_error  # type: ignore[misc]

    async def __call__(
        self,
        context: AgentContext,
        input_data: InputT,
    ) -> AgentResult:
        """Allow agents to be called directly."""
        logger.info(
            "%s executing for mission=%s target=%s phase=%s",
            self.name,
            context.mission_id,
            context.target,
            context.phase,
        )
        result = await self.execute(context, input_data)
        if result.error:
            logger.error("%s failed: %s", self.name, result.error)
        else:
            logger.info(
                "%s completed successfully (action=%s)",
                self.name,
                result.action.action_type if result.action else "none",
            )

        # Send TensorZero feedback for optimization
        if self._last_inference_id:
            try:
                from spectra_ai_core.feedback import send_task_feedback

                await send_task_feedback(self._last_inference_id, success=result.success)
            except Exception:
                logger.debug("Failed to send TZ feedback", exc_info=True)

        return result
