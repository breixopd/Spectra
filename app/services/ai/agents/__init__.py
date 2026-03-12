"""
Agents package for the MAKER Swarm Architecture.
"""

from app.services.ai.agents.base import (
    Agent,
)
from app.services.ai.agents.mission_controller import (
    AssessmentPhase,
    MissionController,
    MissionInput,
    MissionPlan,
    MissionType,
    Task,
)
from app.services.ai.agents.models import (
    ActionRisk,
    AgentAction,
    AgentContext,
    AgentResult,
    AgentRole,
    ApprovalRequest,
    ParallelToolAction,
    SteeringAction,
    ToolAction,
)
from app.services.ai.agents.parameter_tuner import (
    ParameterTunerAgent,
    TunerInput,
    TunerOutput,
)
from app.services.ai.agents.parser import (
    ParsedFinding,
    ParserAgent,
    ParserInput,
    ParserOutput,
)
from app.services.ai.agents.recon_intel import (
    OsintSanitizer,
    ReconIntelAgent,
    ReconIntelInput,
    ReconIntelOutput,
)
from app.services.ai.agents.registry import (
    AgentInfo,
    AgentRegistry,
    get_agent_registry,
    register_agent,
)
from app.services.ai.agents.scope import ScopeAction, ScopeAgent, ScopeInput, TargetSpec
from app.services.ai.agents.tool_selector import (
    ToolSelectorAgent,
    ToolSelectorInput,
    ToolSelectorOutput,
)

__all__ = [
    # Base
    "Agent",
    "AgentRole",
    "AgentContext",
    "AgentAction",
    "AgentResult",
    "ActionRisk",
    "ToolAction",
    "ParallelToolAction",
    "SteeringAction",
    "ApprovalRequest",
    # Registry
    "AgentRegistry",
    "AgentInfo",
    "get_agent_registry",
    "register_agent",
    # Scope
    "ScopeAgent",
    "ScopeInput",
    "ScopeAction",
    "TargetSpec",
    # Tool Selector
    "ToolSelectorAgent",
    "ToolSelectorInput",
    "ToolSelectorOutput",
    # Recon Intel
    "ReconIntelAgent",
    "ReconIntelInput",
    "ReconIntelOutput",
    "OsintSanitizer",
    # Parser
    "ParserAgent",
    "ParserInput",
    "ParserOutput",
    "ParsedFinding",
    # Parameter Tuner
    "ParameterTunerAgent",
    "TunerInput",
    "TunerOutput",
    # Mission Controller
    "MissionController",
    "MissionInput",
    "MissionPlan",
    "Task",
    "AssessmentPhase",
    "MissionType",
]
