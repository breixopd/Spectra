"""Task Dispatcher and Handlers for Mission Executor."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from app.services.ai.agents.tool_selector import ToolSelectorInput

from app.core.constants import MAX_HOSTS_DEFAULT
from app.core.events import events
from app.services.ai.agents.base import AgentContext
from app.services.ai.sanitizer import sanitize_for_prompt
from app.services.ai.agents.base import ParallelToolAction, ToolAction
from app.services.ai.agents.mission_controller import AssessmentPhase, Task
from app.services.ai.output_intelligence import extract_intelligence
from app.services.mission.executor.analysis import auto_expand_scope
from app.services.mission.executor.utils import detect_target_type
from app.services.mission.task_tree import TaskStatus
from app.services.mission.tool_chain_rules import get_triggered_rules

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

from app.core.constants import MAX_CHAIN_DEPTH

if TYPE_CHECKING:
    from app.services.ai.agents.base import BaseAgent
    from app.services.ai.consensus import VotingSystem
    from app.services.mission.exploitation import ExploitationManager
    from app.services.mission.mission import Mission
    from app.services.tools.service import ToolExecutionService

logger = logging.getLogger(__name__)


def _get_known_tools() -> set[str]:
    """Dynamically get known tool names from registry."""
    try:
        from app.services.tools.registry import get_registry

        registry = get_registry()
        if registry:
            return {t.config.id.lower() for t in registry.list_tools()}
    except (ImportError, OSError, RuntimeError, AttributeError) as e:
        logger.debug("Failed to get tool registry: %s", e)
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
            except (OSError, RuntimeError, ValueError):
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
            "tool_selector": self._handle_tool_selector,
            "tool_executor": self._handle_tool_selector,  # Alias: LLMs often say "executor"
            "exploit_crafter": self._handle_exploit_crafter,
            "exploit_verifier": self._handle_exploit_verifier,
            "scope": self._handle_scope,
            "scope_agent": self._handle_scope,  # Alias for LLM consistency
            "reporter": self._handle_reporter,
            "script_runner": self._handle_script_runner,
            "post_exploitation": self._handle_post_exploitation,
            "vector_generator": self._handle_vector_generator,
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
            selector_input = self._build_selector_input(mission, task, context)
            result = await agent.execute(context, selector_input)

            if result.success and isinstance(result.action, ParallelToolAction):
                await self._execute_parallel_selection(
                    mission, result.action, context
                )
            elif result.success and isinstance(result.action, ToolAction):
                await self._execute_single_selection(
                    mission, task, result.action, context
                )
            else:
                mission.log(f"Tool selection failed: {result.error}")

        finally:
            self._broadcast_agent_state("tool_selector", "idle")

    def _build_selector_input(
        self,
        mission: Mission,
        task: Task,
        context: AgentContext,
    ) -> ToolSelectorInput:
        """Build tool selector input from mission state and blackboard."""
        from app.services.ai.agents.tool_selector import ToolSelectorInput

        target_type = detect_target_type(mission.target)

        tool_hint = task.parameters.get("tool_hint") or task.parameters.get("tool")
        if not tool_hint:
            tool_hint = self._extract_tool_hint_from_description(task.description)

        known_services = mission.get_known_services()
        known_vulns = mission.get_known_vulns()

        if mission.blackboard:
            self._enrich_context_from_blackboard(mission, context)

        return ToolSelectorInput(
            current_phase=task.phase.value,
            target=mission.target,
            target_type=target_type,
            known_services=known_services,
            known_vulns=known_vulns,
            tools_already_run=mission.tools_run.copy(),
            user_preference=tool_hint,
            required_capability=task.parameters.get("required_capability"),
            tags_filter=task.parameters.get("tags", []),
        )

    def _enrich_context_from_blackboard(
        self, mission: Mission, context: AgentContext
    ) -> None:
        """Add blackboard intelligence (creds, ports) to agent context."""
        bb_creds = mission.blackboard.read("credentials")
        bb_ports = mission.blackboard.read("open_ports")
        mission.blackboard.read("vulnerabilities")

        if bb_creds and isinstance(bb_creds, list):
            raw = f"Discovered credentials: {bb_creds[:5]}"
            context.extra_context = (
                getattr(context, "extra_context", "")
                + "\n" + sanitize_for_prompt(raw, field_name="blackboard_credentials")
            )
        if bb_ports and isinstance(bb_ports, list):
            raw = f"Discovered open ports: {bb_ports[:20]}"
            context.extra_context = (
                getattr(context, "extra_context", "")
                + "\n" + sanitize_for_prompt(raw, field_name="blackboard_ports")
            )

    async def _execute_parallel_selection(
        self,
        mission: Mission,
        parallel_action: ParallelToolAction,
        context: AgentContext,
    ) -> None:
        """Execute parallel tool selection results."""
        mission.log(
            f"Parallel execution: {[t.tool_name for t in parallel_action.tools]}"
        )
        results = await self._execute_parallel_tools(
            mission, parallel_action, context
        )
        for r in results:
            tool_name = r.get("tool")
            if tool_name:
                await self._process_tool_chain(mission, tool_name, context)

    async def _execute_single_selection(
        self,
        mission: Mission,
        task: Task,
        action: ToolAction,
        context: AgentContext,
    ) -> None:
        """Execute a single tool selection result."""
        if not action.tool_name:
            reason = getattr(action, "skip_reason", "No reason provided")
            mission.log(f"No more tools for phase: {reason}")
            return

        success = await self.tool_service.execute_tool_action(
            mission, action, context
        )

        if success and mission.findings:
            mission.blackboard.write(
                task.agent_type,
                f"tools_run_{action.tool_name}",
                {"tool": action.tool_name, "findings_count": len(mission.findings)},
            )

        if not success:
            mission.log(
                f"Tool {action.tool_name} execution failed or was blocked."
            )

        if success:
            await self._process_tool_chain(
                mission, action.tool_name, context
            )

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

    async def _handle_script_runner(
        self,
        mission: Mission,
        task: Task,
        context: AgentContext,
    ) -> None:
        """Handle custom script execution."""
        self._broadcast_agent_state("script_runner", "running")
        try:
            content = task.parameters.get("content")
            language = task.parameters.get("language", "python")
            target = task.parameters.get("target", mission.target)

            if not content:
                mission.log("Script execution failed: No content provided")
                return

            # Execute
            result = await self.tool_service.execute_custom_script(
                mission, content, language, target
            )

            if result.success:
                mission.log("Custom script executed successfully.")
                if result.stdout:
                    mission.log(f"Output: {result.stdout[:200]}...")

                # If we have exploit metadata, we should save this attempt
                # but for custom scripts, successful execution is step 1.

                # We can update the mission findings/attack surface here if the script output implies success
            else:
                mission.log(f"Script execution failed: {result.stderr[:500]}")

        finally:
            self._broadcast_agent_state("script_runner", "idle")

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
                max_hosts=task.parameters.get("max_hosts", MAX_HOSTS_DEFAULT),
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

    async def _handle_post_exploitation(
        self,
        mission: Mission,
        task: Task,
        context: AgentContext,
    ) -> None:
        """Handle post-exploitation tasks by delegating to tool_selector with post_exploitation phase."""
        self._broadcast_agent_state("post_exploitation", "running")
        try:
            # Gather exploitation context from successful attack vectors
            from app.models.attack_surface import VectorStatus

            successful_vectors = [
                {
                    "name": v.name,
                    "description": v.description,
                    "target": v.target_ref,
                    "tools_used": [a.tool_used for a in v.attempts if a.success],
                }
                for v in mission.attack_surface.vectors
                if v.status == VectorStatus.SUCCESS
            ]
            credentials = mission.attack_surface.credentials
            exploit_findings = [
                f for f in mission.findings
                if f.get("type") == "exploit" or f.get("severity") in ("critical", "high")
            ]

            exploitation_summary = {
                "successful_vectors": successful_vectors,
                "credentials_found": len(credentials),
                "exploit_findings_count": len(exploit_findings),
            }

            # Enrich task description with exploitation context
            enriched_desc = task.description
            if successful_vectors:
                vector_lines = "; ".join(
                    f"{v['name']} on {v['target']}" for v in successful_vectors
                )
                enriched_desc += f"\n\nExploitation context — successful vectors: {vector_lines}"
            if credentials:
                enriched_desc += f"\n\nCredentials discovered: {len(credentials)} set(s) available"
                # Include structured credential details for tool use
                cred_summary = mission.credential_store.get_summary_for_prompt(context.target)
                if cred_summary:
                    enriched_desc += f"\n\n{cred_summary}"

            logger.info(
                "Post-exploitation enrichment: %d successful vectors, %d credentials, %d exploit findings",
                len(successful_vectors),
                len(credentials),
                len(exploit_findings),
            )

            # Post-exploitation reuses tool_selector with the phase set to post_exploitation
            context_copy = AgentContext(
                mission_id=context.mission_id,
                session_id=context.session_id,
                target=context.target,
                mission=context.mission,
            )
            context_copy.phase = "post_exploitation"

            params = dict(task.parameters) if task.parameters else {}
            params["verify_access"] = True
            params["exploitation_summary"] = exploitation_summary

            task_copy = Task(
                task_id=task.task_id,
                description=enriched_desc,
                agent_type="tool_selector",
                phase=AssessmentPhase.POST_EXPLOITATION,
                priority=task.priority,
                parameters=params,
                dependencies=task.dependencies,
            )
            await self._handle_tool_selector(mission, task_copy, context_copy)
        finally:
            self._broadcast_agent_state("post_exploitation", "idle")

    async def _handle_vector_generator(
        self,
        mission: Mission,
        task: Task,
        context: AgentContext,
    ) -> None:
        """Handle attack vector generation from discovered services/vulns."""
        self._broadcast_agent_state("vector_generator", "running")
        try:
            if "vector_generator" in self.agents:
                agent = self.agents["vector_generator"]
                result = await agent.execute(context, {
                    "services": mission.get_known_services(),
                    "vulnerabilities": mission.get_known_vulns(),
                    "target": mission.target,
                })
                if result.success and result.action:
                    vectors = getattr(result.action, "vectors", [])
                    for v in vectors:
                        mission.attack_surface.add_vector(v)
                    mission.log(f"[VECTORS] Generated {len(vectors)} attack vectors")
                else:
                    mission.log(f"Vector generation failed: {result.error}")
            else:
                # Fallback: generate basic vectors from services
                await self.exploitation_manager._generate_basic_vectors(mission)
                mission.log("[VECTORS] Generated basic vectors from known services")
        finally:
            self._broadcast_agent_state("vector_generator", "idle")

    async def _execute_parallel_tools(
        self,
        mission: Mission,
        parallel_action: ParallelToolAction,
        context: AgentContext,
    ) -> list[dict[str, Any]]:
        """Execute multiple tools in parallel with concurrency control."""
        sem = asyncio.Semaphore(parallel_action.max_concurrency)
        completed: list[dict[str, Any]] = []

        async def _run_one(tool_action: ToolAction) -> dict[str, Any]:
            async with sem:
                mission.log(f"Parallel start: {tool_action.tool_name}")
                success = await self.tool_service.execute_tool_action(
                    mission, tool_action, context
                )
                if success and mission.findings:
                    mission.blackboard.write(
                        "tool_selector",
                        f"tools_run_{tool_action.tool_name}",
                        {"tool": tool_action.tool_name, "findings_count": len(mission.findings)},
                    )
                return {"tool": tool_action.tool_name, "success": success}

        results = await asyncio.gather(
            *[_run_one(t) for t in parallel_action.tools],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                logger.error("Parallel tool failed: %s", r)
            else:
                completed.append(r)
        return completed

    async def _process_tool_chain(
        self,
        mission: Mission,
        tool_name: str,
        context: AgentContext,
    ) -> None:
        """Run tool chain rules and output intelligence extraction after tool execution."""
        # Gather recent output from findings/logs
        logs = getattr(mission, "logs", [])
        recent_output = "\n".join(logs[-20:])
        tool_execs = getattr(mission, "tool_executions", [])
        for exec_record in tool_execs[-3:]:
            if exec_record.get("tool") == tool_name:
                recent_output += "\n" + str(exec_record.get("args", ""))

        # 1. Extract intelligence
        intel_items = extract_intelligence(tool_name, recent_output)
        for item in intel_items:
            mission.blackboard.write(
                "output_intelligence",
                f"intel_{item.type}_{item.value[:30]}",
                {"type": item.type, "value": item.value, "confidence": item.confidence,
                 "source": item.source_tool},
            )

        # 1b. Auto-expand scope if new hosts/subdomains discovered
        host_findings = [
            {"type": item.type, "value": item.value}
            for item in intel_items
            if item.type in ("subdomain", "host", "ip")
        ]
        if host_findings:
            current_scope = {"target": mission.target}
            expansions = auto_expand_scope(host_findings, current_scope)
            if expansions:
                for exp in expansions:
                    mission.log(f"[SCOPE] Auto-discovered: {exp['type']} {exp['value']}")
                mission.blackboard.write(
                    "scope", "auto_expansions",
                    {"expansions": expansions},
                )

        # 2. Check chain rules
        host = mission.target
        triggered = get_triggered_rules(tool_name, recent_output, host)

        chain_count = getattr(mission, "_chain_depth", 0)
        for rule, args in triggered:
            if chain_count >= MAX_CHAIN_DEPTH:
                mission.log(f"Auto-chain: max depth ({MAX_CHAIN_DEPTH}) reached, stopping")
                break
            if rule.next_tool in mission.tools_run:
                continue  # Already ran this tool

            mission.log(f"Auto-chain: {tool_name} -> {rule.next_tool} ({rule.description})")

            # Add chained task to plan
            new_task = Task(
                task_id=f"chain-{uuid.uuid4().hex[:8]}",
                description=f"[AUTO-CHAIN] {rule.description}",
                agent_type="tool_selector",
                phase=AssessmentPhase.ENUMERATION,
                priority=rule.priority,
                parameters={"tool_hint": rule.next_tool, **args},
                dependencies=[],
            )
            if mission.plan:
                insert_idx = mission.current_task_index + 1
                mission.plan.tasks.insert(insert_idx, new_task)

            # Track in task tree as child
            parent_id = f"{tool_name}-chain"
            if not mission.task_tree.get_node(parent_id):
                mission.task_tree.add_task(
                    parent_id, f"{tool_name} chains", f"chain/{tool_name}")
            mission.task_tree.add_task(
                new_task.task_id, rule.description[:60],
                f"chain/{rule.next_tool}", parent_id=parent_id,
                tool_used=rule.next_tool,
            )
            chain_count += 1

        mission._chain_depth = chain_count  # type: ignore[attr-defined]

    def should_transition_phase(
        self,
        mission: Mission,
        current_phase: str,
    ) -> bool:
        """Check if we should transition to the next phase based on rules."""
        rules = PHASE_TRANSITION_RULES.get(current_phase)
        if not rules:
            return False

        # Count tools run in this phase
        phase_tool_count = sum(
            1 for e in mission.tool_executions
            if e.get("success", False)
        )

        # Check max tools
        if phase_tool_count >= rules["max_tools"]:
            mission.log(f"Phase {current_phase}: max tools ({rules['max_tools']}) reached, transitioning")
            return True

        # Check min tools
        if phase_tool_count < rules["min_tools"]:
            return False

        trigger = rules.get("transition_trigger", "")
        if trigger == "services_found" and mission.attack_surface.services:
            return True
        if trigger == "vulnerabilities_found" and mission.attack_surface.vulnerabilities:
            return True
        if trigger == "shell_obtained":
            # Check exploit success in logs
            if any("session" in log.lower() or "shell" in log.lower() for log in mission.logs[-10:]):
                return True
        if trigger == "privesc_achieved":
            if any("root" in log.lower() or "system" in log.lower() for log in mission.logs[-10:]):
                return True

        # Check max failures for exploitation
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

        except (OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError) as e:
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
                    pass

        except (OSError, RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.error("Dynamic vector generation failed: %s", e)
