"""
Agents package for the MAKER Swarm Architecture.
"""

from spectra_platform.services.ai.agents.base import (
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
from spectra_platform.services.ai.agents.mission_controller import (
    AssessmentPhase,
    MissionController,
    MissionInput,
    MissionPlan,
    MissionType,
    Task,
)
from spectra_platform.services.ai.agents.recon_intel import (
    OsintSanitizer,
    ReconIntelAgent,
    ReconIntelInput,
    ReconIntelOutput,
)
from spectra_platform.services.ai.agents.registry import (
    AgentInfo,
    AgentRegistry,
    get_agent_registry,
    register_agent,
)
from spectra_platform.services.ai.agents.scope import ScopeAction, ScopeAgent, ScopeInput, TargetSpec
from spectra_platform.services.ai.agents.tool_selector import (
    ToolSelectorAgent,
    ToolSelectorInput,
    ToolSelectorOutput,
)

__all__ = [
    "ActionRisk",
    # Base
    "Agent",
    "AgentAction",
    "AgentContext",
    "AgentInfo",
    # Registry
    "AgentRegistry",
    "AgentResult",
    "AgentRole",
    "ApprovalRequest",
    "AssessmentPhase",
    # Mission Controller
    "MissionController",
    "MissionInput",
    "MissionPlan",
    "MissionType",
    "OsintSanitizer",
    # Recon Intel
    "ReconIntelAgent",
    "ReconIntelInput",
    "ReconIntelOutput",
    "ScopeAction",
    # Scope
    "ScopeAgent",
    "ScopeInput",
    "SteeringAction",
    "TargetSpec",
    "Task",
    "ToolAction",
    # Tool Selector
    "ToolSelectorAgent",
    "ToolSelectorInput",
    "ToolSelectorOutput",
    "get_agent_registry",
    "register_agent",
]
