"""Task Dispatcher and Handlers for Mission Executor."""

from __future__ import annotations

import logging
import re
import uuid
from typing import TYPE_CHECKING, Any, cast, Callable, Awaitable

from app.core.events import events
from app.services.ai.agents.base import AgentContext, ToolAction
from app.services.ai.agents.mission_controller import AssessmentPhase, Task
from app.services.mission.executor.utils import detect_target_type
from app.services.ai.consensus import QualityGate

if TYPE_CHECKING:
    from app.services.mission.mission import Mission
    from app.services.tools.service import ToolExecutionService
    from app.services.mission.exploitation import ExploitationManager
    from app.services.ai.consensus import VotingSystem
    from app.services.ai.agents.base import BaseAgent
    from app.services.ai.agents.tool_selector import ToolSelectorInput
    from app.services.ai.agents.payload_crafter import PayloadCrafterOutput, PayloadCrafterInput
    from app.services.ai.agents.exploit_verifier import ExploitVerifierOutput, ExploitVerifierInput
    from app.services.ai.agents.scope import ScopeInput
    from app.services.ai.agents.reporter import ReporterInput
    from app.services.ai.agents.post_exploitation import PostExploitInput, PostExploitAction

logger = logging.getLogger("spectra.mission.executor.handlers")


def _get_known_tools() -> set[str]:
    """Dynamically get known tool names from registry."""
    try:
        from app.services.tools.registry import get_registry

        registry = get_registry()
        if registry:
            return {t.config.id.lower() for t in registry.list_tools()}
    except Exception:
        pass
    # Fallback if registry not available
    return {
        "nmap",
        "naabu",
        "nuclei",
        "nikto",
        "wpscan",
        "gobuster",
        "ffuf",
        "sqlmap",
        "hydra",
        "metasploit",
        "searchsploit",
        "amass",
    }


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

    async def dispatch(
        self,
        mission: Mission,
        task: Task,
        context: AgentContext,
    ) -> None:
        """Execute a single task with the appropriate agent."""
        handler = self._get_task_handler(task.agent_type)
        if handler:
            await handler(mission, task, context)
        else:
            mission.log(f"Unknown agent type: {task.agent_type}")

    def _get_task_handler(
        self, agent_type: str
    ) -> Callable[[Mission, Task, AgentContext], Awaitable[None]] | None:
        """Get the handler method for an agent type."""
        handlers = {
            "tool_selector": self._handle_tool_selector,
            "exploit_crafter": self._handle_exploit_crafter,
            "payload_crafter": self._handle_payload_crafter,
            "exploit_verifier": self._handle_exploit_verifier,
            "scope": self._handle_scope,
            "scope_agent": self._handle_scope,  # Alias for LLM consistency
            "reporter": self._handle_reporter,
        }
        handler = handlers.get(agent_type)
        if not handler:
            # Fallback for unknown agents (often hallucinations of specific tool agents)
            if agent_type.endswith("_agent") or agent_type in [
                "discovery",
                "enumeration",
                "vulnerability",
            ]:
                return self._handle_tool_selector
        return handler

    def _extract_tool_hint_from_description(self, description: str) -> str | None:
        """Extract tool name from task description if mentioned."""
        desc_lower = description.lower()
        known_tools = _get_known_tools()

        # Look for common patterns like "using nmap", "with nuclei", "run gobuster"
        patterns = [
            r"\busing\s+(\w+)",
            r"\bwith\s+(\w+)",
            r"\brun\s+(\w+)",
            r"\buse\s+(\w+)",
            r"\bperform.*?\s+(\w+)\s+scan",
            r"^(\w+)\s+scan",
        ]

        for pattern in patterns:
            match = re.search(pattern, desc_lower)
            if match:
                tool_candidate = match.group(1)
                if tool_candidate in known_tools:
                    logger.debug(
                        "Extracted tool hint '%s' from description: %s",
                        tool_candidate,
                        description[:50],
                    )
                    return tool_candidate

        # Direct mention check
        for tool in known_tools:
            if tool in desc_lower:
                logger.debug(
                    "Found tool '%s' in description: %s", tool, description[:50]
                )
                return tool

        return None

    def _broadcast_agent_state(self, agent_id: str, status: str, **kwargs) -> None:
        """Broadcast agent state via EventBus."""
        # We emit an event, and the EventWebSocketBridge handles the broadcasting
        events.emit_sync(
            "agent_state",
            "mission_executor",
            agent_id=agent_id,
            status=status,
            **kwargs,
        )

    async def _handle_tool_selector(
        self,
        mission: Mission,
        task: Task,
        context: AgentContext,
    ) -> None:
        """Handle tool selection and execution task."""
        self._broadcast_agent_state("tool_selector", "running")
        agent = self.agents["tool_selector"]

        try:
            # Detect target type from format
            target_type = detect_target_type(mission.target)

            # Build comprehensive input from mission state
            from app.services.ai.agents.tool_selector import ToolSelectorInput

            # Try to extract tool hint from task parameters or description
            tool_hint = task.parameters.get("tool_hint")
            if not tool_hint:
                # Fallback: try to extract tool name from task description
                tool_hint = self._extract_tool_hint_from_description(task.description)

            selector_input = ToolSelectorInput(
                current_phase=task.phase.value,
                target=mission.target,
                target_type=target_type,
                known_services=mission.get_known_services(),
                known_vulns=mission.get_known_vulns(),
                tools_already_run=mission.tools_run.copy(),
                user_preference=tool_hint,
                required_capability=task.parameters.get("required_capability"),
                tags_filter=task.parameters.get("tags", []),
            )

            result = await agent.execute(context, selector_input)

            if result.success and isinstance(result.action, ToolAction):
                action = result.action

                # Skip if no tool selected (phase complete)
                if not action.tool_name:
                    reason = getattr(result.action, "skip_reason", "No reason provided")
                    mission.log(f"No more tools for phase: {reason}")
                    return

                # Delegate execution to Tool Service
                success = await self.tool_service.execute_tool_action(
                    mission, action, context
                )

                if not success:
                    mission.log(
                        f"Tool {action.tool_name} execution failed or was blocked."
                    )
            else:
                mission.log(f"Tool selection failed: {result.error}")

        finally:
            self._broadcast_agent_state("tool_selector", "idle")

    async def _handle_exploit_crafter(
        self,
        mission: Mission,
        task: Task,
        context: AgentContext,
    ) -> None:
        """Handle exploitation phase."""
        self._broadcast_agent_state("exploit_crafter", "running")
        try:
            await self.exploitation_manager.run_iterative_exploitation(mission, context)
        finally:
            self._broadcast_agent_state("exploit_crafter", "idle")

    async def _handle_payload_crafter(
        self,
        mission: Mission,
        task: Task,
        context: AgentContext,
    ) -> None:
        """Handle payload crafting task with quality gate validation."""
        self._broadcast_agent_state("payload_crafter", "running")
        agent = self.agents["payload_crafter"]

        try:
            vuln_data = task.parameters.get("vulnerability", {})
            if not vuln_data and mission.attack_surface.vulnerabilities:
                vuln = mission.attack_surface.vulnerabilities[0]
                vuln_data = vuln.dict()

            if not vuln_data:
                mission.log("Skipping payload crafting: No vulnerability data found")
            else:
                from app.services.ai.agents.payload_crafter import (
                    PayloadCrafterInput,
                    PayloadCrafterOutput,
                )

                crafter_input = PayloadCrafterInput(
                    vulnerability=vuln_data,
                    target=mission.target,
                    target_os=task.parameters.get("target_os"),
                    protocol=task.parameters.get("protocol"),
                )

                result = await agent.execute(context, crafter_input)

                if result.success and result.action:
                    action = cast(PayloadCrafterOutput, result.action)

                    # Validate payload at quality gate
                    mission.log(f"[VALIDATE] Payload: {action.exploit_name}")
                    vote_result = await self.consensus.validate_at_gate(
                        QualityGate.PAYLOAD,
                        action,
                        {
                            "target": mission.target,
                            "vulnerability": vuln_data.get("name", "unknown"),
                            "exploit": action.exploit_name,
                            "payload_type": action.payload_type,
                            "has_custom_script": bool(action.custom_script),
                        },
                    )

                    if vote_result.status != "approved":
                        mission.log(
                            f"[REJECTED] Payload rejected: {vote_result.escalation_reason}"
                        )
                        return

                    mission.log(
                        f"[APPROVED] Crafted payload: {action.exploit_name} ({action.payload_type})"
                    )

                    # Create follow-up task
                    new_task = Task(
                        task_id=f"exploit-{uuid.uuid4().hex[:8]}",
                        description=f"Execute {action.exploit_name} against {mission.target}",
                        agent_type="tool_selector",
                        phase=AssessmentPhase.EXPLOITATION,
                        priority=1,
                        parameters={
                            "tool_hint": action.exploit_name,
                            "target": mission.target,
                            "args": {"payload": action.payload_type},
                        },
                        dependencies=[task.task_id],
                    )

                    if mission.plan:
                        mission.plan.tasks.append(new_task)
                        mission.log(
                            f"[PLAN] Added execution task for {action.exploit_name}"
                        )
                else:
                    mission.log(f"Payload crafting failed: {result.error}")
        finally:
            self._broadcast_agent_state("payload_crafter", "idle")

    async def _handle_exploit_verifier(
        self,
        mission: Mission,
        task: Task,
        context: AgentContext,
    ) -> None:
        """Handle exploit verification task."""
        self._broadcast_agent_state("exploit_verifier", "running")
        agent = self.agents["exploit_verifier"]

        try:
            target = task.parameters.get("target", mission.target)
            exploit_output = task.parameters.get("exploit_output", "")
            expected_outcome = task.parameters.get(
                "expected_outcome", "successful exploitation"
            )

            # Try to get output from last attempt
            if not exploit_output and mission.attack_surface.vectors:
                for vector in reversed(mission.attack_surface.vectors):
                    if vector.attempts:
                        last_attempt = vector.attempts[-1]
                        exploit_output = last_attempt.output
                        target = vector.target_ref
                        break

            if not exploit_output:
                mission.log("Skipping verification: No exploit output found")
            else:
                from app.services.ai.agents.exploit_verifier import (
                    ExploitVerifierInput,
                    ExploitVerifierOutput,
                )

                verifier_input = ExploitVerifierInput(
                    target=target,
                    exploit_output=exploit_output,
                    expected_outcome=expected_outcome,
                    connection_details=None,
                )

                result = await agent.execute(context, verifier_input)

                if result.success and result.action:
                    action = cast(ExploitVerifierOutput, result.action)
                    mission.log(
                        f"Verification: {'Success' if action.is_successful else 'Failed'} "
                        f"(Confidence: {action.confidence:.2f})"
                    )
                    mission.log(f"Proof: {action.proof}")

                    if action.is_successful:
                        mission.log(
                            "Exploit verified! Proceeding to post-exploitation..."
                        )
                else:
                    mission.log(f"Verification failed: {result.error}")

        finally:
            self._broadcast_agent_state("exploit_verifier", "idle")

    async def _handle_scope(
        self,
        mission: Mission,
        task: Task,
        context: AgentContext,
    ) -> None:
        """Handle scope refinement task."""
        self._broadcast_agent_state("scope_agent", "running")
        agent = self.agents["scope_agent"]
        try:
            mission.log("Refining scope...")
            
            from app.services.ai.agents.scope import ScopeInput

            scope_input = ScopeInput(
                raw_input=mission.target,
                include_subdomains=task.parameters.get("include_subdomains", True),
                max_hosts=task.parameters.get("max_hosts", 256),
            )

            result = await agent.execute(context, scope_input)
            if result.success and result.action:
                mission.log(
                    f"Scope refined: {len(result.action.targets)} targets"  # type: ignore
                )
        finally:
            self._broadcast_agent_state("scope_agent", "idle")

    async def _handle_reporter(
        self,
        mission: Mission,
        task: Task,
        context: AgentContext,
    ) -> None:
        """Handle report generation task."""
        self._broadcast_agent_state("reporter", "running")
        agent = self.agents["reporter"]
        try:
            mission.log("[INFO] Generating assessment report...")

            from app.services.ai.agents.reporter import ReporterInput, ReportOutput

            reporter_input = ReporterInput(
                findings=mission.findings,
                mission_summary=mission.directive,
                target=mission.target,
            )

            result = await agent.execute(context, reporter_input)
            if result.success and result.action:
                report = cast(ReportOutput, result.action)
                # Save report path to mission
                if report.report_path:
                    mission.report_path = report.report_path
                    mission.log(f"[REPORT] Report saved to: {report.report_path}")

                # Log summary statistics
                total = (
                    report.critical_count
                    + report.high_count
                    + report.medium_count
                    + report.low_count
                    + report.info_count
                )
                mission.log(
                    f"[STATS] Report Summary: {total} findings "
                    f"(Critical: {report.critical_count}, High: {report.high_count}, "
                    f"Medium: {report.medium_count}, Low: {report.low_count}, Info: {report.info_count})"
                )
                mission.log("[SUCCESS] Report generated successfully")
            else:
                mission.log(f"[ERROR] Report generation failed: {result.error}")
        finally:
            self._broadcast_agent_state("reporter", "idle")

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
                    await self._generate_dynamic_vectors(mission, context, "service", svc.dict())

            if finding.get("severity") and finding.get("name"):
                vuln = mission.add_vulnerability(
                    vuln_id=finding.get("id", f"vuln-{uuid.uuid4().hex[:8]}"),
                    title=finding["name"],
                    severity=finding["severity"],
                    cve_id=finding.get("cve_id"),
                )
                if context and "vector_generator" in self.agents:
                    await self._generate_dynamic_vectors(mission, context, "vulnerability", vuln.dict())

            if finding.get("url") and finding.get("technologies"):
                app = mission.add_webapp(
                    url=finding["url"],
                    technologies=finding.get("technologies", []),
                )
                if context and "vector_generator" in self.agents:
                    await self._generate_dynamic_vectors(mission, context, "webapp", app.dict())

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
            # Need strict import to avoid circular dependency if top-level
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
                    # Broadcast vector update? Mission handles it internally via add_vector logging?
                    # Executor used _broadcast("vector_update").
                    # We can leave it for now or implement _broadcast method in Dispatcher (it has one).
                    # self._broadcast("vector_update", vector.model_dump(mode="json"))
                    pass

        except Exception as e:
            logger.error("Dynamic vector generation failed: %s", e)
