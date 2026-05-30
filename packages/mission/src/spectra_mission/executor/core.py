"""Core Mission Executor module."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from spectra_ai_core.agents.base import AgentRole
from spectra_ai_core.agents.registry import get_agent_registry
from spectra_ai_core.consensus import VotingSystem
from spectra_mission.executor.handlers import TaskDispatcher
from spectra_mission.exploitation import ExploitationManager
from spectra_tools.service import ToolExecutionService

if TYPE_CHECKING:
    from spectra_ai_core.agents.base import Agent, AgentContext
    from spectra_ai_core.agents.mission_controller import Task
    from spectra_ai_core.llm import LLMClient
    from spectra_mission.mission import Mission

logger = logging.getLogger(__name__)

# Agent dict keys mapped to their AgentRole enum values
_REQUIRED_AGENTS: dict[str, AgentRole] = {
    "tool_selector": AgentRole.TOOL_SELECTOR,
    "scope_agent": AgentRole.SCOPE,
    "exploit_crafter": AgentRole.EXPLOIT_CRAFTER,
    "exploit_verifier": AgentRole.EXPLOIT_VERIFIER,
    "reporter": AgentRole.REPORTER,
    "vector_generator": AgentRole.VECTOR_GENERATOR,
    "post_exploitation": AgentRole.POST_EXPLOITATION,
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

        # All agents created exclusively through the registry
        self.agents = self._init_agents(llm)

        # Dispatcher handles routing and execution logic
        self.dispatcher = TaskDispatcher(
            tool_service=self.tool_service,
            exploitation_manager=self.exploitation_manager,
            consensus=self.consensus,
            agents=self.agents,
        )

    def _init_agents(self, llm: LLMClient) -> dict[str, Agent]:  # type: ignore[type-arg]
        """Create all agents from the registry. Raises on missing registration."""
        registry = get_agent_registry()
        agents: dict[str, Agent] = {}  # type: ignore[type-arg]
        for key, role in _REQUIRED_AGENTS.items():
            agents[key] = registry.create(role, llm)
            logger.debug("Initialized agent %s (role=%s)", key, role)
        return agents

    async def execute_task(
        self,
        mission: Mission,
        task: Task,
        context: AgentContext,
    ) -> None:
        """Execute a single task with the appropriate agent."""
        logger.info("Starting task %s for mission %s (user_id=%s)", task.task_id, mission.id, mission.user_id)
        try:
            await self.dispatcher.dispatch(mission, task, context)
            logger.info("Task %s completed for mission %s", task.task_id, mission.id)
        except Exception as e:
            mission.log(f"Task execution failed: {e}")
            logger.error("Error executing task %s: %s", task.task_id, e, exc_info=True)
            raise
