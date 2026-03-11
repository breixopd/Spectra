"""Base Agent class for the MAKER Swarm Architecture."""

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.services.ai.llm import LLMClient
from app.services.ai.prompts import BASE_SYSTEM_PROMPT

logger = logging.getLogger("spectra.ai.agents")


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


class ActionRisk(StrEnum):
    """Risk level of an agent action."""

    LOW = "low"  # Safe to execute automatically
    MEDIUM = "medium"  # Requires logging
    HIGH = "high"  # Requires voting/consensus
    CRITICAL = "critical"  # Requires human approval


# --- Context Models ---


class AgentContext(BaseModel):
    """Context passed to agents for decision making."""

    mission_id: str = Field(..., description="Current mission ID")
    session_id: str | None = Field(None, description="Current session ID (optional)")
    target: str | None = Field(None, description="Current target (IP/domain)")
    mission: str | None = Field(None, description="High-level mission directive")
    phase: str = Field("discovery", description="Current assessment phase")

    # State from previous actions
    previous_findings: list[dict[str, Any]] = Field(default_factory=list)
    previous_actions: list[dict[str, Any]] = Field(default_factory=list)
    available_tools: list[str] = Field(default_factory=list)

    # Constraints
    stealth_mode: bool = Field(False, description="Minimize detection")
    max_concurrency: int = Field(3, description="Max parallel operations")

    # Extra context from blackboard/intelligence
    extra_context: str = Field("", description="Additional context from blackboard")


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
    tool_args: dict[str, Any] = Field(
        default_factory=dict, description="Tool arguments"
    )
    target: str = Field(..., description="Target for the tool")
    estimated_duration: int = Field(60, description="Estimated duration in seconds")


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

# Maps AgentRole → task_type string used by LiteLLMRouter for tier routing
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
}


InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=AgentAction)


class Agent(ABC, Generic[InputT, OutputT]):
    """Base class for all MAKER agents."""

    role: ClassVar[AgentRole]
    name: ClassVar[str] = "BaseAgent"
    description: ClassVar[str] = "Base agent class"

    # Default system prompt template
    system_prompt_template: ClassVar[str] = BASE_SYSTEM_PROMPT

    def __init__(self, llm: LLMClient):
        """
        Initialize the agent with an LLM client.

        Args:
            llm: The LLM client to use for generation.
        """
        self.llm = llm

    @property
    def _task_type(self) -> str | None:
        """Get the task_type string for this agent's role (used for tier routing)."""
        return ROLE_TASK_MAP.get(self.role)

    async def _llm_generate(self, **kwargs: Any) -> Any:
        """Call self.llm.generate() with automatic task_type injection."""
        kwargs.setdefault("task_type", self._task_type)
        return await self.llm.generate(**kwargs)

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

    def _get_temperature(self, input_data: Any, attempt: int = 1) -> float:
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
        """Check if an action requires human approval."""
        from app.core.config import settings

        if not settings.REQUIRE_APPROVAL:
            return False

        return action.risk_level in (ActionRisk.HIGH, ActionRisk.CRITICAL)

    def requires_consensus(self, action: OutputT) -> bool:
        """Check if an action requires consensus voting."""
        return action.risk_level == ActionRisk.HIGH

    def broadcast_thought(self, content: str) -> None:
        """
        Broadcast a thought/reasoning step to the UI.

        This enables the 'Stream of Consciousness' display.
        """
        from app.core.events import EventType, events

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
            except Exception as exc:
                last_error = exc
                if attempt < max_retries:
                    delay = backoff_factor ** attempt
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
        return await self.execute(context, input_data)
