"""Base Agent class for the MAKER Swarm Architecture."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel, Field

from app.services.ai.llm import LLMClient
from app.services.ai.prompts import BASE_SYSTEM_PROMPT

logger = logging.getLogger("spectra.ai.agents")


# --- Enums ---


class AgentRole(str, Enum):
    """Defines the role/responsibility of an agent."""

    SCOPE = "scope"  # Parses input to define boundaries
    TOOL_SELECTOR = "tool_selector"  # Chooses the right tool
    PARAMETER_TUNER = "parameter_tuner"  # Adjusts tool parameters
    PARSER = "parser"  # Parses tool output
    MISSION_CONTROLLER = "mission_controller"  # Orchestrates workflow
    SAFETY_SUPERVISOR = "safety_supervisor"  # Blocks dangerous actions
    EXPLOIT_CRAFTER = "exploit_crafter"  # Crafts exploits
    EXPLOIT_VERIFIER = "exploit_verifier"  # Verifies exploit success


class ActionRisk(str, Enum):
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


# --- Action Models ---


class AgentAction(BaseModel):
    """Base class for agent actions/decisions."""

    action_type: str = Field(..., description="Type of action to take")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score")
    risk_level: ActionRisk = Field(ActionRisk.LOW, description="Risk assessment")
    reasoning: str = Field(..., description="Explanation for the decision")

    class Config:
        use_enum_values = True
        # Pydantic V2 compatibility
        from pydantic import ConfigDict

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

    def _get_temperature(self, input_data: Any) -> float:
        """
        Determine the temperature for LLM generation based on task complexity.

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
            return 0.1
        elif self.role == AgentRole.EXPLOIT_CRAFTER:
            return 0.7
        elif self.role == AgentRole.MISSION_CONTROLLER:
            return 0.4
        else:
            return 0.3

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

    async def __call__(
        self,
        context: AgentContext,
        input_data: InputT,
    ) -> AgentResult:
        """Allow agents to be called directly."""
        return await self.execute(context, input_data)
