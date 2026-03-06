"""Mission execution logic."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

from app.core.events import events
from app.core.constants import (
    DEBRIEF_MAX_FINDINGS,
    DEBRIEF_MAX_LOGS,
    DEBRIEF_SUMMARY_LOG_CHARS,
    MAX_HOSTS_DEFAULT,
)
from app.services.ai.agents.base import AgentContext, SteeringAction
from app.services.ai.agents.mission_controller import (
    MissionController,
    MissionInput,
    MissionPlan,
)
from app.services.ai.agents.scope import ScopeAgent, ScopeInput
from app.services.ai.consensus import QualityGate, VotingSystem
from app.services.ai.llm import get_global_llm_client
from app.services.mission.executor import MissionExecutor
from app.services.mission.mission import Mission
from app.services.mission.manager.lifecycle import MissionLifecycleManager
from app.services.mission.manager.steering import MissionSteeringManager
from app.services.shell.session_manager import shell_manager

logger = logging.getLogger("spectra.mission.manager.execution")


class MissionExecutionManager:
    """Manages the execution flow of missions."""

    def __init__(
        self,
        lifecycle: MissionLifecycleManager,
        steering: MissionSteeringManager,
    ):
        self.lifecycle = lifecycle
        self.steering = steering
        self.mission_controller: MissionController | None = None
        self.scope_agent: ScopeAgent | None = None
        self.executor: MissionExecutor | None = None
        self.consensus: VotingSystem | None = None

    async def ensure_agents(self) -> None:
        """Initialize agents with current LLM client."""
        current_llm = await get_global_llm_client()
        self.mission_controller = MissionController(current_llm)
        self.scope_agent = ScopeAgent(current_llm)
        self.executor = MissionExecutor(current_llm)
        self.consensus = VotingSystem(current_llm)

    async def run_mission_loop(self, mission: Mission) -> None:
        """Main execution loop for a mission."""
        # Initialize demo recorder if requested
        recorder = None
        if getattr(mission, "record_demo", False):
            try:
                from app.services.mission.demo_recorder import DemoRecorder

                recorder = DemoRecorder(mission.id, mission.target)
                recorder.start()
                mission.log("[RECORD] Demo recording started")
            except Exception:
                pass

        context = await self.lifecycle.initialize_mission(mission)
        if context is None:
            return

        # Send start notification
        try:
            from app.services.notifications import notify_mission_started

            await notify_mission_started(mission.target, mission.directive)
        except Exception:
            pass

        try:
            # 1. Define Scope
            await self._run_scope_phase(mission, context)

            # 2. Create and validate plan
            await self._run_planning_phase(mission, context)

            if mission.plan is None:
                raise RuntimeError("No plan created")

            # 3. Execute tasks (with demo recording)
            if recorder:
                mission._demo_recorder = recorder
            await self._execute_mission_tasks(mission, context)

            # 4. Post-mission learning
            self._record_mission_lessons(mission)

            # 5. Run AI debrief
            await self._run_debrief(mission, context)

            # 6. Generate HTML report
            self._generate_html_report(mission)

            # 7. Complete
            mission.set_status("completed")
            mission.log("Mission completed successfully")
            self._broadcast_state("mission_controller", "idle", plan="Mission Complete")

            # Save demo recording
            if recorder:
                path = recorder.stop()
                recorder.save()
                if path:
                    mission.log(f"[RECORD] Demo saved: {path}")

            # Send completion notification
            try:
                from app.services.notifications import notify_mission_completed

                critical = sum(
                    1
                    for f in mission.findings
                    if str(f.get("severity", "")).lower() == "critical"
                )
                await notify_mission_completed(
                    mission.target, len(mission.findings), critical
                )
            except Exception:
                pass

            # Update DB
            await self.lifecycle.update_db_status(mission)

        except asyncio.CancelledError:
            mission.set_status("cancelled")
            mission.log("Mission cancelled")
            logger.info("Mission %s cancelled", mission.id)
            self._broadcast_state("mission_controller", "cancelled")
            await self.lifecycle.update_db_status(mission)
        except Exception as e:
            mission.set_status("failed")
            mission.log(f"Mission failed: {e}")
            logger.error("Mission %s failed: %s", mission.id, e, exc_info=True)
            self._broadcast_state("mission_controller", "failed")
            await self.lifecycle.update_db_status(mission)
        finally:
            # Notify shell manager to update TTLs for active shells from other missions
            try:
                shell_manager.notify_mission_complete(str(mission.id))
            except Exception as e:
                logger.error(
                    f"Failed to notify shell manager of mission completion: {e}"
                )

    async def _run_scope_phase(self, mission: Mission, context: AgentContext) -> None:
        """Run scope definition phase."""
        mission.log("Defining scope...")
        self._broadcast_state("scope_agent", "running")

        if not self.scope_agent:
            raise RuntimeError("Scope agent not initialized")

        scope_result = await self.scope_agent.execute(
            context,
            ScopeInput(
                raw_input=mission.target,
                include_subdomains=True,
                max_hosts=MAX_HOSTS_DEFAULT,
            ),
        )

        self._broadcast_state("scope_agent", "idle")

        if not scope_result.success:
            raise RuntimeError(f"Scoping failed: {scope_result.error}")

        target_count = len(scope_result.action.targets)  # type: ignore
        mission.log(f"Scope defined: {target_count} targets")

    async def _run_planning_phase(
        self, mission: Mission, context: AgentContext
    ) -> None:
        """Run mission planning phase with quality gate validation."""
        mission.log("Generating mission plan...")

        if not self.mission_controller:
            raise RuntimeError("Mission controller not initialized")

        plan_result = await self.mission_controller.execute(
            context,
            MissionInput(
                directive=mission.directive,
                is_steering=False,
                force_phase=None,
            ),
        )

        if not plan_result.success:
            error_msg = plan_result.error or "Unknown error"
            if "404" in error_msg and "data policy" in error_msg:
                error_msg += " (Check LLM provider settings/data policy)"
            raise RuntimeError(f"Planning failed: {error_msg}")

        plan_action = cast(MissionPlan, plan_result.action)

        # Validate plan at PLAN quality gate - thorough validation
        mission.log("[VALIDATE] Mission plan at PLAN gate...")
        self._broadcast(
            "consensus_vote_start",
            {
                "action": "mission_plan",
                "gate": "plan",
                "reasoning": f"Validating strategy for {len(plan_action.tasks)} tasks",
            },
        )

        if not self.consensus:
            raise RuntimeError("Consensus system not initialized")

        vote_result = await self.consensus.validate_at_gate(
            QualityGate.PLAN,
            plan_action,
            {
                "target": mission.target,
                "directive": mission.directive,
                "task_count": len(plan_action.tasks),
                "mission_type": plan_action.mission_type,
                "phases": list({t.phase.value for t in plan_action.tasks}),
            },
        )

        self._broadcast("consensus_vote_result", vote_result.model_dump())

        if vote_result.status != "approved":
            raise RuntimeError(f"Plan rejected: {vote_result.escalation_reason}")

        mission.log(
            f"[APPROVED] Plan validated (Confidence: {vote_result.average_confidence:.2f})"
        )
        mission.plan = plan_action

        task_count = len(mission.plan.tasks)
        mission.log(f"Plan created: {task_count} tasks")
        self._broadcast_state(
            "mission_controller", "running", plan=f"{task_count} tasks planned"
        )

    async def _execute_mission_tasks(
        self, mission: Mission, context: AgentContext
    ) -> None:
        """Execute all mission tasks with dynamic plan adaptation.

        Tasks are grouped by phase and independent tasks within the same phase
        run in parallel via ``asyncio.gather``.  Tasks with unmet dependencies
        execute sequentially after the independent batch completes.
        """
        if mission.plan is None:
            return

        # Track findings count for adaptation triggers
        last_findings_count = len(mission.findings)
        last_adaptation_index = -1

        # Group tasks by phase while preserving order
        phase_groups: dict[str, list[tuple[int, Any]]] = {}
        for i, task in enumerate(mission.plan.tasks):
            phase = task.phase.value
            if phase not in phase_groups:
                phase_groups[phase] = []
            phase_groups[phase].append((i, task))

        global_task_counter = 0

        for phase, indexed_tasks in phase_groups.items():
            if mission.is_stopped():
                mission.log("Mission stopped by user")
                break

            await mission.wait_if_paused()

            # Skip entire phase if requested
            if phase in mission.skipped_phases:
                for _, task in indexed_tasks:
                    mission.log(f"Skipping task '{task.description}' (phase skipped)")
                global_task_counter += len(indexed_tasks)
                continue

            # Track completed task IDs within this mission
            completed_task_ids: set[str] = set()

            # Partition into independent and dependent tasks
            independent = [
                (i, t)
                for i, t in indexed_tasks
                if not t.dependencies
                or all(d in completed_task_ids for d in t.dependencies)
            ]
            dependent = [
                (i, t) for i, t in indexed_tasks if (i, t) not in independent
            ]

            # --- Run independent tasks in parallel ---
            if independent:
                async def _run_task(
                    idx: int,
                    task: Any,
                    _context: AgentContext = context,
                ) -> None:
                    """Execute a single task with full lifecycle handling."""
                    mission.current_task_index = idx
                    total = len(mission.plan.tasks) if mission.plan else 0
                    mission.log(
                        f"[TASK] Executing task [{idx + 1}/{total}]: {task.description}"
                    )
                    _context_copy = AgentContext(
                        mission_id=_context.mission_id,
                        session_id=_context.session_id,
                        target=_context.target,
                        mission=_context.mission,
                    )
                    _context_copy.phase = task.phase.value

                    if not self.executor:
                        raise RuntimeError("Executor not initialized")
                    await self.executor.execute_task(mission, task, _context_copy)

                results = await asyncio.gather(
                    *[_run_task(idx, t) for idx, t in independent],
                    return_exceptions=True,
                )

                for (idx, task), result in zip(independent, results):
                    if isinstance(result, Exception):
                        await self._handle_task_failure(
                            mission, task, str(result), context
                        )
                        await self.lifecycle.update_db_status(mission)
                    else:
                        completed_task_ids.add(task.task_id)
                        # Check plan adaptation after each successful task
                        current_findings = len(mission.findings)
                        new_findings = current_findings - last_findings_count
                        effective_idx = global_task_counter + independent.index(
                            (idx, task)
                        )
                        if (
                            new_findings >= 3
                            and effective_idx > last_adaptation_index + 2
                        ):
                            await self._adapt_plan_to_findings(
                                mission, context, new_findings
                            )
                            last_adaptation_index = effective_idx
                            last_findings_count = current_findings
                        await self.lifecycle.update_db_status(mission)

            # --- Run dependent tasks sequentially ---
            for idx, task in dependent:
                if mission.is_stopped():
                    mission.log("Mission stopped by user")
                    break

                await mission.wait_if_paused()

                mission.current_task_index = idx
                total = len(mission.plan.tasks) if mission.plan else 0
                mission.log(
                    f"[TASK] Executing task [{idx + 1}/{total}]: {task.description}"
                )
                context.phase = task.phase.value

                try:
                    if not self.executor:
                        raise RuntimeError("Executor not initialized")
                    await self.executor.execute_task(mission, task, context)
                    completed_task_ids.add(task.task_id)

                    current_findings = len(mission.findings)
                    new_findings = current_findings - last_findings_count
                    effective_idx = global_task_counter + len(independent) + dependent.index(
                        (idx, task)
                    )
                    if (
                        new_findings >= 3
                        and effective_idx > last_adaptation_index + 2
                    ):
                        await self._adapt_plan_to_findings(
                            mission, context, new_findings
                        )
                        last_adaptation_index = effective_idx
                        last_findings_count = current_findings

                    await self.lifecycle.update_db_status(mission)
                except Exception as e:
                    await self._handle_task_failure(mission, task, str(e), context)
                    await self.lifecycle.update_db_status(mission)

            global_task_counter += len(indexed_tasks)

    async def _adapt_plan_to_findings(
        self, mission: Mission, context: AgentContext, new_findings_count: int
    ) -> None:
        """Adapt mission plan based on new findings (PTES/MAKER methodology)."""
        mission.log(
            f"[ADAPT] {new_findings_count} new findings discovered. Evaluating plan adaptation..."
        )

        try:
            # Summarize recent findings for context
            recent_findings = mission.findings[-new_findings_count:]
            critical_high = [
                f
                for f in recent_findings
                if str(f.get("severity", "")).lower() in ("critical", "high")
            ]

            if not critical_high:
                mission.log(
                    "[ADAPT] No critical/high findings - continuing with current plan"
                )
                return

            finding_summary = "; ".join(
                [
                    f"{f.get('title', 'Unknown')} ({f.get('severity', 'unknown')})"
                    for f in critical_high[:5]
                ]
            )

            # Ask mission controller to adapt
            adapt_directive = (
                f"ADAPT PLAN: New critical findings discovered: {finding_summary}. "
                f"Current attack surface: {mission.attack_surface.get_summary()}. "
                f"Prioritize exploitation of these findings following PTES methodology. "
                f"Add specific tasks to exploit the discovered vulnerabilities."
            )

            input_data = MissionInput(
                directive=adapt_directive,
                is_steering=True,
                force_phase=None,
            )

            if not self.mission_controller:
                return

            result = await self.mission_controller.execute(context, input_data)

            if result.success and result.action:
                if isinstance(result.action, SteeringAction):
                    mission.log(f"[ADAPT] Plan adapted: {result.action.reasoning}")
                    await self.steering.apply_steering_action(mission, result.action)
                elif isinstance(result.action, MissionPlan):
                    # New tasks suggested - add to existing plan
                    new_tasks = result.action.tasks
                    if new_tasks and mission.plan:
                        # Insert new tasks after current position
                        insert_pos = mission.current_task_index + 1
                        for j, new_task in enumerate(
                            new_tasks[:5]
                        ):  # Limit to 5 new tasks
                            mission.plan.tasks.insert(insert_pos + j, new_task)
                        mission.log(
                            f"[ADAPT] Added {len(new_tasks[:5])} new tasks to plan"
                        )
            else:
                mission.log("[ADAPT] Plan adaptation not needed")

        except Exception as e:
            logger.warning("Plan adaptation failed: %s", e)
            mission.log(f"[ADAPT] Adaptation failed: {e}")

    async def _handle_task_failure(
        self,
        mission: Mission,
        task: Any,
        error: str,
        context: AgentContext,
    ) -> None:
        """Handle task failure with adaptive replanning and quality gate validation."""
        mission.log(f"[ADAPT] Task '{task.description}' failed. Replanning...")

        try:
            input_data = MissionInput(
                directive=f"Task '{task.description}' failed: {error}. Adapt the plan.",
                is_steering=True,
                force_phase=None,
            )

            if not self.mission_controller:
                raise RuntimeError("Mission controller not initialized")

            result = await self.mission_controller.execute(context, input_data)

            if result.success and result.action:
                if isinstance(result.action, SteeringAction):
                    # Validate replan at REPLAN quality gate
                    mission.log("[VALIDATE] Replan at REPLAN gate...")
                    if not self.consensus:
                        raise RuntimeError("Consensus system not initialized")

                    vote_result = await self.consensus.validate_at_gate(
                        QualityGate.REPLAN,
                        result.action,
                        {
                            "target": mission.target,
                            "failed_task": task.description,
                            "error": error[:200],
                            "new_direction": result.action.reasoning,
                        },
                    )

                    if vote_result.status != "approved":
                        mission.log(
                            f"[REJECTED] Replan rejected: {vote_result.escalation_reason}"
                        )
                        mission.log("[ADAPT] Continuing with original plan")
                        return

                    mission.log("[APPROVED] Replan validated")
                    await self.steering.apply_steering_action(mission, result.action)
                else:
                    mission.log("[ADAPT] Unexpected action type from controller")
            else:
                mission.log(f"[ADAPT] Replanning failed: {result.error}")

        except Exception as e:
            logger.error("Adaptive replanning failed: %s", e, exc_info=True)
            mission.log(f"[ADAPT] Critical failure: {e}")

    async def _run_debrief(self, mission: Mission, context: AgentContext) -> None:
        """Run AI debrief analysis after mission completion."""
        try:
            from app.services.ai.agents.debrief import DebriefAgent, DebriefInput

            if not self.mission_controller:
                return

            debrief = DebriefAgent(self.mission_controller.llm)
            debrief_input = DebriefInput(
                target=mission.target,
                directive=mission.directive,
                findings=mission.findings[:DEBRIEF_MAX_FINDINGS],
                tools_run=mission.tools_run,
                logs=mission.logs[-DEBRIEF_MAX_LOGS:],
                attack_surface_summary=mission.attack_surface.get_summary(),
            )

            result = await debrief.execute(context, debrief_input)
            if result.success and result.action:
                action = result.action
                mission.log(f"[DEBRIEF] Risk: {action.risk_rating.upper()}")
                mission.log(f"[DEBRIEF] {action.executive_summary[:DEBRIEF_SUMMARY_LOG_CHARS]}")
                for lesson in action.lessons_learned[:3]:
                    mission.log(f"[LEARN] {lesson}")
        except Exception as e:
            logger.debug("Debrief failed (non-critical): %s", e)

    def _generate_html_report(self, mission: Mission) -> None:
        """Generate HTML report from mission data."""
        try:
            from app.services.mission.report_generator import (
                generate_html_report,
                save_report,
            )

            report_data = {
                "mission": {
                    "id": mission.id,
                    "target": mission.target,
                    "directive": mission.directive,
                    "name": f"Assessment of {mission.target}",
                    "summary": mission.to_dict().get("summary", {}),
                },
                "findings": mission.findings,
                "attack_surface": {
                    "services": [
                        {"host": s.host, "port": s.port, "service": s.service, "product": s.product, "version": s.version}
                        for s in mission.attack_surface.services
                    ] if mission.attack_surface else [],
                },
                "tools_used": mission.tools_run or [],
            }
            html = generate_html_report(report_data)
            path = save_report(mission.id, html)
            if path:
                mission.report_path = path
                mission.log(f"Report saved: {path}")
        except Exception as e:
            logger.debug("HTML report generation failed: %s", e)

    def _record_mission_lessons(self, mission: Mission) -> None:
        """Extract lessons from the completed mission and persist them."""
        try:
            from app.services.ai.memory import get_memory

            memory = get_memory()

            # Detect duplicate/low-value finding templates as false positives
            template_counts: dict[str, int] = {}
            for finding in mission.findings:
                template = finding.get("template-id") or finding.get("name", "")
                if template:
                    template_counts[template] = template_counts.get(template, 0) + 1

            for template, count in template_counts.items():
                severity = next(
                    (
                        f.get("severity", "info")
                        for f in mission.findings
                        if (f.get("template-id") or f.get("name")) == template
                    ),
                    "info",
                )
                if count >= 5 and severity == "info":
                    memory.record_false_positive(template)
                    mission.log(
                        f"[LEARN] Marked '{template}' as probable false positive ({count} duplicates)"
                    )

            # Record OS profile if detected
            os_family = getattr(mission, "_detected_os", None)
            if os_family and os_family != "unknown":
                services = [
                    s.service for s in mission.attack_surface.services if s.service
                ]
                memory.update_target_profile(
                    os_family,
                    services=services,
                    note=f"Mission against {mission.target}: {len(mission.findings)} findings, "
                    f"{len(mission.tools_run)} tools used",
                )

            stats = memory.get_stats()
            mission.log(
                f"[LEARN] Memory updated: {stats['tool_lessons']} tool lessons, "
                f"{stats['exploit_lessons']} exploit patterns, {stats['target_profiles']} OS profiles"
            )

        except Exception as e:
            logger.debug("Post-mission learning failed (non-critical): %s", e)

    def _broadcast_state(self, agent_id: str, status: str, **kwargs) -> None:
        """Broadcast agent state."""
        self._broadcast(
            "agent_state", {"agent_id": agent_id, "status": status, **kwargs}
        )

    def _broadcast(self, msg_type: str, data: Any) -> None:
        """Broadcast to WebSocket clients via EventBus."""
        events.emit_sync(msg_type, "mission_manager", **data)
