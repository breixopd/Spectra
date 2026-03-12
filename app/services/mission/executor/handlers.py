"""Task Dispatcher and Handlers for Mission Executor."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from app.core.events import events
from app.services.ai.agents.base import AgentContext
from app.services.ai.agents.mission_controller import Task
from app.services.mission.executor.exploit_handlers import ExploitHandlers
from app.services.mission.executor.recon_handlers import (
    MAX_CHAIN_DEPTH,  # noqa: F401 — re-exported for backward compat
    ReconHandlers,
    _get_known_tools,  # noqa: F401 — re-exported for backward compat
)
from app.services.mission.task_tree import TaskStatus

# Phase transition rules for autonomous decision making
PHASE_TRANSITION_RULES: dict[str, dict[str, Any]] = {
    "recon": {
        "min_tools": 2,
        "max_tools": 6,
        "transition_trigger": "services_found",
    },
    "vuln_scan": {
        "min_tools": 1,
        "max_tools": 4,
        "transition_trigger": "vulnerabilities_found",
    },
    "exploitation": {
        "min_tools": 1,
        "max_tools": 5,
        "max_failures": 3,
        "transition_trigger": "shell_obtained",
    },
    "post_exploitation": {
        "min_tools": 1,
        "max_tools": 3,
        "transition_trigger": "privesc_achieved",
    },
}

if TYPE_CHECKING:
    from app.services.ai.agents.base import BaseAgent
    from app.services.ai.consensus import VotingSystem
    from app.services.mission.exploitation import ExploitationManager
    from app.services.mission.mission import Mission
    from app.services.tools.service import ToolExecutionService

logger = logging.getLogger("spectra.mission.executor.handlers")


class TaskDispatcher:
    """Dispatches tasks to the appropriate agent handlers."""

    def __init__(
        self,
        tool_service: ToolExecutionService,
        exploitation_manager: ExploitationManager,
        consensus: VotingSystem,
        agents: dict[str, BaseAgent],
    ):
        self.tool_service = tool_service
        self.exploitation_manager = exploitation_manager
        self.consensus = consensus
        self.agents = agents

        # Initialize sub-handler groups
        self._recon = ReconHandlers(tool_service, agents, self._broadcast_agent_state)
        self._exploit = ExploitHandlers(
            tool_service, exploitation_manager, agents,
            self._broadcast_agent_state,
            self._recon.handle_tool_selector,
        )

    async def dispatch(
        self,
        mission: Mission,
        task: Task,
        context: AgentContext,
    ) -> None:
        """Execute a single task with the appropriate agent."""
        # Wire blackboard context into agent context
        bb_context = mission.blackboard.get_context_for_agent(task.agent_type)
        if bb_context:
            context.extra_context = getattr(context, "extra_context", "") + "\n" + bb_context

        # Track task in task tree
        task_tree_id = f"{task.phase.value}-{task.task_id}"
        mission.task_tree.add_task(
            task_tree_id,
            task.description[:80],
            f"{task.phase.value}/{task.agent_type}",
            tool_used=task.parameters.get("tool_hint"),
        )
        mission.task_tree.update_status(task_tree_id, TaskStatus.ACTIVE)

        handler = self._get_task_handler(task.agent_type)
        if handler:
            try:
                await handler(mission, task, context)
                mission.task_tree.update_status(task_tree_id, TaskStatus.COMPLETED)
            except Exception:
                mission.task_tree.update_status(task_tree_id, TaskStatus.FAILED)
                raise
        else:
            mission.log(f"Unknown agent type: {task.agent_type}")
            mission.task_tree.update_status(task_tree_id, TaskStatus.SKIPPED)

    def _get_task_handler(
        self, agent_type: str
    ) -> Callable[[Mission, Task, AgentContext], Awaitable[None]] | None:
        """Get the handler method for an agent type."""
        handlers = {
            "tool_selector": self._recon.handle_tool_selector,
            "tool_executor": self._recon.handle_tool_selector,
            "exploit_crafter": self._exploit.handle_exploit_crafter,
            "exploit_verifier": self._exploit.handle_exploit_verifier,
            "scope": self._recon.handle_scope,
            "scope_agent": self._recon.handle_scope,
            "reporter": self._recon.handle_reporter,
            "script_runner": self._recon.handle_script_runner,
            "post_exploitation": self._exploit.handle_post_exploitation,
            "vector_generator": self._exploit.handle_vector_generator,
        }
        handler = handlers.get(agent_type)
        if not handler:
            if agent_type.endswith("_agent") or agent_type in [
                "discovery",
                "enumeration",
                "vulnerability",
            ]:
                return self._recon.handle_tool_selector
        return handler

    def _broadcast_agent_state(self, agent_id: str, status: str, **kwargs) -> None:
        """Broadcast agent state via EventBus."""
        events.emit_sync(
            "agent_state",
            "mission_executor",
            agent_id=agent_id,
            status=status,
            **kwargs,
        )

    def should_transition_phase(
        self,
        mission: Mission,
        current_phase: str,
    ) -> bool:
        """Check if we should transition to the next phase based on rules."""
        rules = PHASE_TRANSITION_RULES.get(current_phase)
        if not rules:
            return False

        phase_tool_count = sum(
            1 for e in mission.tool_executions
            if e.get("success", False)
        )

        if phase_tool_count >= rules["max_tools"]:
            mission.log(f"Phase {current_phase}: max tools ({rules['max_tools']}) reached, transitioning")
            return True

        if phase_tool_count < rules["min_tools"]:
            return False

        trigger = rules.get("transition_trigger", "")
        if trigger == "services_found" and mission.attack_surface.services:
            return True
        if trigger == "vulnerabilities_found" and mission.attack_surface.vulnerabilities:
            return True
        if trigger == "shell_obtained":
            if any("session" in log.lower() or "shell" in log.lower() for log in mission.logs[-10:]):
                return True
        if trigger == "privesc_achieved":
            if any("root" in log.lower() or "system" in log.lower() for log in mission.logs[-10:]):
                return True

        max_failures = rules.get("max_failures")
        if max_failures:
            failure_count = sum(
                1 for e in mission.tool_executions
                if not e.get("success", False)
            )
            if failure_count >= max_failures:
                mission.log(
                    f"Phase {current_phase}: {failure_count} failures reached max ({max_failures}), transitioning")
                return True

        return False

    async def _update_attack_surface(
        self,
        mission: Mission,
        finding: dict[str, Any],
        context: AgentContext | None = None,
    ) -> None:
        """Update attack surface from findings."""
        try:
            if finding.get("port"):
                svc = mission.add_service(
                    host=finding.get("host", mission.target),
                    port=finding["port"],
                    service=finding.get("service"),
                    product=finding.get("product"),
                    version=finding.get("version"),
                )
                if context and "vector_generator" in self.agents:
                    await self._generate_dynamic_vectors(
                        mission, context, "service", svc.model_dump()
                    )

            if finding.get("severity") and finding.get("name"):
                vuln = mission.add_vulnerability(
                    vuln_id=finding.get("id", f"vuln-{uuid.uuid4().hex[:8]}"),
                    title=finding["name"],
                    severity=finding["severity"],
                    cve_id=finding.get("cve_id"),
                )
                if context and "vector_generator" in self.agents:
                    await self._generate_dynamic_vectors(
                        mission, context, "vulnerability", vuln.model_dump()
                    )

            if finding.get("url") and finding.get("technologies"):
                app = mission.add_webapp(
                    url=finding["url"],
                    technologies=finding.get("technologies", []),
                )
                if context and "vector_generator" in self.agents:
                    await self._generate_dynamic_vectors(
                        mission, context, "webapp", app.model_dump()
                    )

        except Exception as e:
            logger.warning("Failed to update attack surface: %s", e)

    async def _generate_dynamic_vectors(
        self,
        mission: Mission,
        context: AgentContext,
        target_type: str,
        target_data: dict[str, Any],
    ) -> None:
        """Generate attack vectors using AI."""
        if "vector_generator" not in self.agents:
            return

        agent = self.agents["vector_generator"]
        try:
            from app.services.ai.agents.vector_generator import VectorGeneratorInput

            input_data = VectorGeneratorInput(
                target_type=target_type,
                target_data=target_data,
                context_notes=f"Mission: {mission.directive}",
            )

            result = await agent.execute(context, input_data)

            if result.success and result.action:
                for vector in result.action.vectors:  # type: ignore
                    mission.attack_surface.add_vector(vector)
                    mission.log(f"Generated vector: {vector.name} ({vector.priority})")

        except Exception as e:
            logger.error("Dynamic vector generation failed: %s", e)
