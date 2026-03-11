"""Core Mission Executor module."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.ai.agents.base import AgentRole

# Direct imports kept as fallbacks
from app.services.ai.agents.exploit_crafter import ExploitCrafter
from app.services.ai.agents.exploit_verifier import ExploitVerifierAgent
from app.services.ai.agents.post_exploitation import PostExploitationAgent
from app.services.ai.agents.registry import get_agent_registry
from app.services.ai.agents.reporter import ReporterAgent
from app.services.ai.agents.scope import ScopeAgent

# Agents
from app.services.ai.agents.tool_selector import ToolSelectorAgent
from app.services.ai.agents.vector_generator import VectorGeneratorAgent
from app.services.ai.consensus import VotingSystem
from app.services.mission.executor.handlers import TaskDispatcher
from app.services.mission.exploitation import ExploitationManager
from app.services.tools.service import ToolExecutionService

if TYPE_CHECKING:
    from app.services.ai.agents.base import Agent, AgentContext
    from app.services.ai.agents.mission_controller import Task
    from app.services.ai.llm import LLMClient
    from app.services.mission.mission import Mission

logger = logging.getLogger("spectra.mission.executor")

# Maps agent dict key -> (AgentRole, fallback class)
_AGENT_ROLE_MAP: dict[str, tuple[AgentRole, type[Agent]]] = {  # type: ignore[type-arg]
    "tool_selector": (AgentRole.TOOL_SELECTOR, ToolSelectorAgent),
    "scope_agent": (AgentRole.SCOPE, ScopeAgent),
    "exploit_crafter": (AgentRole.EXPLOIT_CRAFTER, ExploitCrafter),
    "exploit_verifier": (AgentRole.EXPLOIT_VERIFIER, ExploitVerifierAgent),
    "reporter": (AgentRole.REPORTER, ReporterAgent),
    "vector_generator": (AgentRole.VECTOR_GENERATOR, VectorGeneratorAgent),
    "post_exploitation": (AgentRole.POST_EXPLOITATION, PostExploitationAgent),
}


class MissionExecutor:
    """
    Executes mission tasks and exploitation phases.

    Responsibilities:
    - Execute individual tasks using appropriate agents (via TaskDispatcher)
    - Delegate tool execution to ToolExecutionService
    - Delegate exploitation to ExploitationManager
    - Validate decisions at quality gates
    """

    def __init__(self, llm: LLMClient):
        """Initialize executor with required agents."""
        self.llm = llm

        # Core Services
        self.tool_service = ToolExecutionService(llm)
        self.exploitation_manager = ExploitationManager(llm, self.tool_service)
        self.consensus = VotingSystem(llm)

        # Task execution agents — prefer registry, fall back to direct init
        self.agents = self._init_agents_from_registry(llm)

        # Dispatcher handles routing and execution logic
        self.dispatcher = TaskDispatcher(
            tool_service=self.tool_service,
            exploitation_manager=self.exploitation_manager,
            consensus=self.consensus,
            agents=self.agents,
        )

    def _init_agents_from_registry(self, llm: LLMClient) -> dict[str, Agent]:  # type: ignore[type-arg]
        """Create agents using the registry, falling back to direct instantiation."""
        registry = get_agent_registry()
        agents: dict[str, Agent] = {}  # type: ignore[type-arg]
        for key, (role, fallback_cls) in _AGENT_ROLE_MAP.items():
            try:
                agents[key] = registry.create(role, llm)
            except KeyError:
                logger.warning(
                    "Agent for role %s not in registry, using fallback %s",
                    role,
                    fallback_cls.__name__,
                )
                agents[key] = fallback_cls(llm)
        return agents

    async def execute_task(
        self,
        mission: Mission,
        task: Task,
        context: AgentContext,
    ) -> None:
        """Execute a single task with the appropriate agent."""
        try:
            await self.dispatcher.dispatch(mission, task, context)
        except Exception as e:
            mission.log(f"Task execution failed: {e}")
            logger.error("Error executing task %s: %s", task.task_id, e, exc_info=True)
            raise
