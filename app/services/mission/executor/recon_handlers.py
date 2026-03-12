"""Reconnaissance and discovery phase handlers for mission execution."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import TYPE_CHECKING, Any

from app.services.ai.agents.base import AgentContext, ParallelToolAction, ToolAction
from app.services.ai.agents.mission_controller import AssessmentPhase, Task
from app.services.ai.output_intelligence import extract_intelligence
from app.services.mission.executor.analysis import auto_expand_scope
from app.services.mission.executor.utils import detect_target_type
from app.services.mission.tool_chain_rules import get_triggered_rules

MAX_CHAIN_DEPTH = 10

if TYPE_CHECKING:
    from app.services.ai.agents.base import BaseAgent
    from app.services.mission.mission import Mission
    from app.services.tools.service import ToolExecutionService

logger = logging.getLogger("spectra.mission.executor.recon_handlers")


def _get_known_tools() -> set[str]:
    """Dynamically get known tool names from registry."""
    try:
        from app.services.tools.registry import get_registry

        registry = get_registry()
        if registry:
            return {t.config.id.lower() for t in registry.list_tools()}
    except Exception as e:
        logger.debug("Failed to get tool registry: %s", e)
    return {
        "nmap", "naabu", "nuclei", "nikto", "wpscan", "gobuster",
        "ffuf", "sqlmap", "hydra", "metasploit", "searchsploit", "amass",
    }


def extract_tool_hint_from_description(description: str) -> str | None:
    """Extract tool name from task description if mentioned."""
    desc_lower = description.lower()
    known_tools = _get_known_tools()

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

    for tool in known_tools:
        if tool in desc_lower:
            logger.debug(
                "Found tool '%s' in description: %s", tool, description[:50]
            )
            return tool

    return None


class ReconHandlers:
    """Handlers for reconnaissance/discovery and scope-related tasks."""

    def __init__(
        self,
        tool_service: ToolExecutionService,
        agents: dict[str, BaseAgent],
        broadcast_fn: Any,
    ):
        self.tool_service = tool_service
        self.agents = agents
        self._broadcast = broadcast_fn

    async def handle_tool_selector(
        self,
        mission: Mission,
        task: Task,
        context: AgentContext,
    ) -> None:
        """Handle tool selection and execution task."""
        self._broadcast("tool_selector", "running")
        agent = self.agents["tool_selector"]

        try:
            target_type = detect_target_type(mission.target)

            from app.services.ai.agents.tool_selector import ToolSelectorInput

            tool_hint = task.parameters.get("tool_hint") or task.parameters.get("tool")
            if not tool_hint:
                tool_hint = extract_tool_hint_from_description(task.description)

            known_services = mission.get_known_services()
            known_vulns = mission.get_known_vulns()

            if mission.blackboard:
                bb_creds = mission.blackboard.read("credentials")
                bb_ports = mission.blackboard.read("open_ports")
                mission.blackboard.read("vulnerabilities")
                if bb_creds and isinstance(bb_creds, list):
                    context.extra_context = (
                        getattr(context, "extra_context", "")
                        + f"\nDiscovered credentials: {bb_creds[:5]}"
                    )
                if bb_ports and isinstance(bb_ports, list):
                    context.extra_context = (
                        getattr(context, "extra_context", "")
                        + f"\nDiscovered open ports: {bb_ports[:20]}"
                    )

            selector_input = ToolSelectorInput(
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

            if getattr(agent, 'enable_reflection', False) is True:
                result = await agent.execute_with_reflection(context, selector_input)
            else:
                result = await agent.execute(context, selector_input)

            if result.success and isinstance(result.action, ParallelToolAction):
                parallel_action = result.action
                mission.log(
                    f"Parallel execution: {[t.tool_name for t in parallel_action.tools]}"
                )
                results = await self._execute_parallel_tools(
                    mission, parallel_action, context
                )
                for r in results:
                    tool_name = r.get("tool")
                    if tool_name:
                        await self.process_tool_chain(mission, tool_name, context)

            elif result.success and isinstance(result.action, ToolAction):
                action = result.action

                if not action.tool_name:
                    reason = getattr(result.action, "skip_reason", "No reason provided")
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
                    await self.process_tool_chain(
                        mission, action.tool_name, context
                    )
            else:
                mission.log(f"Tool selection failed: {result.error}")

        finally:
            self._broadcast("tool_selector", "idle")

    async def handle_scope(
        self,
        mission: Mission,
        task: Task,
        context: AgentContext,
    ) -> None:
        """Handle scope refinement task."""
        from app.core.constants import MAX_HOSTS_DEFAULT

        self._broadcast("scope_agent", "running")
        agent = self.agents["scope_agent"]
        try:
            mission.log("Refining scope...")

            from app.services.ai.agents.scope import ScopeInput

            scope_input = ScopeInput(
                raw_input=mission.target,
                include_subdomains=task.parameters.get("include_subdomains", True),
                max_hosts=task.parameters.get("max_hosts", MAX_HOSTS_DEFAULT),
            )

            if getattr(agent, 'enable_reflection', False) is True:
                result = await agent.execute_with_reflection(context, scope_input)
            else:
                result = await agent.execute(context, scope_input)
            if result.success and result.action:
                mission.log(
                    f"Scope refined: {len(result.action.targets)} targets"  # type: ignore
                )
        finally:
            self._broadcast("scope_agent", "idle")

    async def handle_reporter(
        self,
        mission: Mission,
        task: Task,
        context: AgentContext,
    ) -> None:
        """Handle report generation task."""
        from typing import cast

        self._broadcast("reporter", "running")
        agent = self.agents["reporter"]
        try:
            mission.log("[INFO] Generating assessment report...")

            from app.services.ai.agents.reporter import ReporterInput, ReportOutput

            reporter_input = ReporterInput(
                findings=mission.findings,
                mission_summary=mission.directive,
                target=mission.target,
            )

            if getattr(agent, 'enable_reflection', False) is True:
                result = await agent.execute_with_reflection(context, reporter_input)
            else:
                result = await agent.execute(context, reporter_input)
            if result.success and result.action:
                report = cast(ReportOutput, result.action)
                if report.report_path:
                    mission.report_path = report.report_path
                    mission.log(f"[REPORT] Report saved to: {report.report_path}")

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
            self._broadcast("reporter", "idle")

    async def handle_script_runner(
        self,
        mission: Mission,
        task: Task,
        context: AgentContext,
    ) -> None:
        """Handle custom script execution."""
        self._broadcast("script_runner", "running")
        try:
            content = task.parameters.get("content")
            language = task.parameters.get("language", "python")
            target = task.parameters.get("target", mission.target)

            if not content:
                mission.log("Script execution failed: No content provided")
                return

            result = await self.tool_service.execute_custom_script(
                mission, content, language, target
            )

            if result.success:
                mission.log("Custom script executed successfully.")
                if result.stdout:
                    mission.log(f"Output: {result.stdout[:200]}...")
            else:
                mission.log(f"Script execution failed: {result.stderr[:500]}")

        finally:
            self._broadcast("script_runner", "idle")

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

    async def process_tool_chain(
        self,
        mission: Mission,
        tool_name: str,
        context: AgentContext,
    ) -> None:
        """Run tool chain rules and output intelligence extraction after tool execution."""
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
                continue

            mission.log(f"Auto-chain: {tool_name} -> {rule.next_tool} ({rule.description})")

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
