"""Data models for the MAKER Swarm Architecture agents."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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

    # Blackboard reference for direct agent writes (excluded from serialization)
    blackboard: Any | None = Field(None, description="Mission blackboard reference", exclude=True)

    # Cost tracking (excluded from serialization)
    cost_tracker: Any | None = Field(None, description="CostTracker instance", exclude=True)


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
    max_concurrency: int = Field(3, description="Max parallel tool executions")


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
