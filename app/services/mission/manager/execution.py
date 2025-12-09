"""Mission execution logic."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

from app.core.events import events
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
        context = await self.lifecycle.initialize_mission(mission)
        if context is None:
            return  # Initialization failed

        try:
            # 1. Define Scope
            await self._run_scope_phase(mission, context)

            # 2. Create and validate plan
            await self._run_planning_phase(mission, context)

            if mission.plan is None:
                raise RuntimeError("No plan created")

            # 3. Execute tasks
            await self._execute_mission_tasks(mission, context)

            # 4. Complete
            mission.set_status("completed")
            mission.log("Mission completed successfully")
            self._broadcast_state("mission_controller", "idle", plan="Mission Complete")

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
                logger.error(f"Failed to notify shell manager of mission completion: {e}")

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
                max_hosts=256,
            ),
        )

        self._broadcast_state("scope_agent", "idle")

        if not scope_result.success:
            raise RuntimeError(f"Scoping failed: {scope_result.error}")

        target_count = len(scope_result.action.targets)  # type: ignore
        mission.log(f"Scope defined: {target_count} targets")

    async def _run_planning_phase(self, mission: Mission, context: AgentContext) -> None:
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

        mission.log(f"[APPROVED] Plan validated (Confidence: {vote_result.average_confidence:.2f})")
        mission.plan = plan_action

        task_count = len(mission.plan.tasks)
        mission.log(f"Plan created: {task_count} tasks")
        self._broadcast_state("mission_controller", "running", plan=f"{task_count} tasks planned")

    async def _execute_mission_tasks(self, mission: Mission, context: AgentContext) -> None:
        """Execute all mission tasks with dynamic plan adaptation."""
        if mission.plan is None:
            return

        # Track findings count for adaptation triggers
        last_findings_count = len(mission.findings)
        last_adaptation_index = -1

        for i, task in enumerate(mission.plan.tasks):
            if mission.is_stopped():
                mission.log("Mission stopped by user")
                break

            await mission.wait_if_paused()

            if task.phase.value in mission.skipped_phases:
                mission.log(f"Skipping task '{task.description}' (phase skipped)")
                continue

            mission.current_task_index = i
            mission.log(
                f"[TASK] Executing task [{i + 1}/{len(mission.plan.tasks)}]: {task.description}"
            )
            context.phase = task.phase.value

            try:
                if not self.executor:
                    raise RuntimeError("Executor not initialized")
                await self.executor.execute_task(mission, task, context)

                # Check if we should adapt the plan based on new findings
                current_findings = len(mission.findings)
                new_findings = current_findings - last_findings_count

                # Adapt plan if significant new findings discovered (PTES/MAKER methodology)
                if new_findings >= 3 and i > last_adaptation_index + 2:
                    await self._adapt_plan_to_findings(mission, context, new_findings)
                    last_adaptation_index = i
                    last_findings_count = current_findings

                # Persist state after each task
                await self.lifecycle.update_db_status(mission)
            except Exception as e:
                await self._handle_task_failure(mission, task, str(e), context)
                # Persist state after failure handling
                await self.lifecycle.update_db_status(mission)

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
                        mission.log(f"[REJECTED] Replan rejected: {vote_result.escalation_reason}")
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

    def _broadcast_state(self, agent_id: str, status: str, **kwargs) -> None:
        """Broadcast agent state."""
        self._broadcast("agent_state", {"agent_id": agent_id, "status": status, **kwargs})

    def _broadcast(self, msg_type: str, data: Any) -> None:
        """Broadcast to WebSocket clients via EventBus."""
        events.emit_sync(msg_type, "mission_manager", **data)
