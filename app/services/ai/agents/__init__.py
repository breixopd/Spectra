"""
Agents package for the MAKER Swarm Architecture.
"""

from app.services.ai.agents.base import (
    ActionRisk,
    Agent,
    AgentAction,
    AgentContext,
    AgentResult,
    AgentRole,
    ApprovalRequest,
    SteeringAction,
    ToolAction,
)
from app.services.ai.agents.mission_controller import (
    AssessmentPhase,
    MissionController,
    MissionInput,
    MissionPlan,
    MissionType,
    Task,
)
from app.services.ai.agents.scope import ScopeAction, ScopeAgent, ScopeInput, TargetSpec
from app.services.ai.agents.tool_selector import ToolSelectorAgent, ToolSelectorInput, ToolSelectorOutput

__all__ = [
    # Base
    "Agent",
    "AgentRole",
    "AgentContext",
    "AgentAction",
    "AgentResult",
    "ActionRisk",
    "ToolAction",
    "SteeringAction",
    "ApprovalRequest",
    # Scope
    "ScopeAgent",
    "ScopeInput",
    "ScopeAction",
    "TargetSpec",
    # Tool Selector
    "ToolSelectorAgent",
    "ToolSelectorInput",
    "ToolSelectorOutput",
    # Mission Controller
    "MissionController",
    "MissionInput",
    "MissionPlan",
    "Task",
    "AssessmentPhase",
    "MissionType",
]
