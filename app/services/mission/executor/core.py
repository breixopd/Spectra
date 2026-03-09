"""Core Mission Executor module."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.ai.agents.exploit_crafter import ExploitCrafter
from app.services.ai.agents.exploit_verifier import ExploitVerifierAgent
from app.services.ai.agents.post_exploitation import PostExploitationAgent
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
    from app.services.ai.agents.base import AgentContext
    from app.services.ai.agents.mission_controller import Task
    from app.services.ai.llm import LLMClient
    from app.services.mission.mission import Mission

logger = logging.getLogger("spectra.mission.executor")


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

        # Task execution agents
        exploit_crafter = ExploitCrafter(llm)
        self.agents = {
            "tool_selector": ToolSelectorAgent(llm),
            "scope_agent": ScopeAgent(llm),
            "exploit_crafter": exploit_crafter,
            "exploit_verifier": ExploitVerifierAgent(llm),
            "reporter": ReporterAgent(llm),
            "vector_generator": VectorGeneratorAgent(llm),
            "post_exploitation": PostExploitationAgent(llm),
        }

        # Dispatcher handles routing and execution logic
        self.dispatcher = TaskDispatcher(
            tool_service=self.tool_service,
            exploitation_manager=self.exploitation_manager,
            consensus=self.consensus,
            agents=self.agents,
        )

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
