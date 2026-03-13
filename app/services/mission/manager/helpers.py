"""Mission execution helper functions: debrief, reporting, plan adaptation, task execution."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from app.core.constants import (
    DEBRIEF_MAX_FINDINGS,
    DEBRIEF_MAX_LOGS,
    DEBRIEF_SUMMARY_LOG_CHARS,
    MISSION_TIMEOUT_SECONDS,
)
from app.services.ai.agents.base import AgentContext, SteeringAction
from app.services.ai.agents.mission_controller import (
    MissionInput,
    MissionPlan,
)
from app.services.ai.consensus import QualityGate, VotingSystem

if TYPE_CHECKING:
    from app.services.ai.agents.mission_controller import MissionController
    from app.services.mission.executor import MissionExecutor
    from app.services.mission.manager.lifecycle import MissionLifecycleManager
    from app.services.mission.manager.steering import MissionSteeringManager
    from app.services.mission.mission import Mission

logger = logging.getLogger(__name__)


async def run_debrief(
    mission: Mission,
    context: AgentContext,
    mission_controller: MissionController | None,
) -> None:
    """Run AI debrief analysis after mission completion."""
    try:
        from app.services.ai.agents.debrief import DebriefAgent, DebriefInput

        if not mission_controller:
            return

        debrief = DebriefAgent(mission_controller.llm)
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
            mission.log(
                f"[DEBRIEF] {action.executive_summary[:DEBRIEF_SUMMARY_LOG_CHARS]}"
            )
            for lesson in action.lessons_learned[:3]:
                mission.log(f"[LEARN] {lesson}")

            try:
                from app.services.ai.memory import get_memory

                memory = get_memory()
                for lesson in action.lessons_learned[:5]:
                    memory.record_tool_lesson(
                        tool="debrief",
                        lesson=lesson,
                        context=f"Mission {mission.id} against {mission.target}",
                    )
            except Exception:
                logger.debug("Failed to persist debrief lessons (non-critical)")
    except Exception as e:
        logger.debug("Debrief failed (non-critical): %s", e)


async def generate_html_report(mission: Mission) -> None:
    """Generate HTML report from mission data."""
    try:
        from app.services.mission.report_generator import (
            generate_html_report as _gen,
        )
        from app.services.mission.report_generator import (
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
                    {
                        "host": s.host,
                        "port": s.port,
                        "service": s.service,
                        "product": s.product,
                        "version": s.version,
                    }
                    for s in mission.attack_surface.services
                ]
                if mission.attack_surface
                else [],
            },
            "tools_used": mission.tools_run or [],
        }
        html = _gen(report_data)
        path = await save_report(mission.id, html)
        if path:
            mission.report_path = path
            mission.log(f"Report saved: {path}")
    except Exception as e:
        logger.warning("HTML report generation failed: %s", e)


async def adapt_plan_to_findings(
    mission: Mission,
    context: AgentContext,
    new_findings_count: int,
    mission_controller: MissionController | None,
    steering: MissionSteeringManager,
) -> None:
    """Adapt mission plan based on new findings (PTES/MAKER methodology)."""
    mission.log(
        f"[ADAPT] {new_findings_count} new findings discovered. Evaluating plan adaptation..."
    )

    try:
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

        if not mission_controller:
            return

        result = await mission_controller.execute(context, input_data)

        if result.success and result.action:
            if isinstance(result.action, SteeringAction):
                mission.log(f"[ADAPT] Plan adapted: {result.action.reasoning}")
                await steering.apply_steering_action(mission, result.action)
            elif isinstance(result.action, MissionPlan):
                new_tasks = result.action.tasks
                if new_tasks and mission.plan:
                    insert_pos = mission.current_task_index + 1
                    for j, new_task in enumerate(new_tasks[:5]):
                        mission.plan.tasks.insert(insert_pos + j, new_task)
                    mission.log(
                        f"[ADAPT] Added {len(new_tasks[:5])} new tasks to plan"
                    )
        else:
            mission.log("[ADAPT] Plan adaptation not needed")

    except Exception as e:
        logger.warning("Plan adaptation failed: %s", e)
        mission.log(f"[ADAPT] Adaptation failed: {e}")


async def handle_task_failure(
    mission: Mission,
    task: Any,
    error: str,
    context: AgentContext,
    mission_controller: MissionController | None,
    consensus: VotingSystem | None,
    steering: MissionSteeringManager,
) -> None:
    """Handle task failure with adaptive replanning and quality gate validation."""
    mission.log(f"[ADAPT] Task '{task.description}' failed. Replanning...")

    try:
        input_data = MissionInput(
            directive=f"Task '{task.description}' failed: {error}. Adapt the plan.",
            is_steering=True,
            force_phase=None,
        )

        if not mission_controller:
            raise RuntimeError("Mission controller not initialized")

        result = await mission_controller.execute(context, input_data)

        if result.success and result.action:
            if isinstance(result.action, SteeringAction):
                mission.log("[VALIDATE] Replan at REPLAN gate...")
                if not consensus:
                    raise RuntimeError("Consensus system not initialized")

                vote_result = await consensus.validate_at_gate(
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
                await steering.apply_steering_action(mission, result.action)
            else:
                mission.log("[ADAPT] Unexpected action type from controller")
        else:
            mission.log(f"[ADAPT] Replanning failed: {result.error}")

    except Exception as e:
        logger.error("Adaptive replanning failed: %s", e, exc_info=True)
        mission.log(f"[ADAPT] Critical failure: {e}")


async def execute_mission_tasks(
    mission: Mission,
    context: AgentContext,
    executor: MissionExecutor | None,
    mission_controller: MissionController | None,
    consensus: VotingSystem | None,
    steering: MissionSteeringManager,
    lifecycle: MissionLifecycleManager,
) -> None:
    """Execute all mission tasks with dynamic plan adaptation.

    Tasks are grouped by phase; independent tasks within the same phase
    run in parallel via ``asyncio.gather``.
    """
    if mission.plan is None:
        return

    last_findings_count = len(mission.findings)
    last_adaptation_index = -1

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

        elapsed = time.time() - getattr(mission, '_start_wall_time', time.time())
        if elapsed > MISSION_TIMEOUT_SECONDS:
            mission.log(
                f"[TIMEOUT] Mission timed out after {int(elapsed)}s "
                f"(limit: {MISSION_TIMEOUT_SECONDS}s)"
            )
            mission.set_status("timed_out")
            break

        await mission.wait_if_paused()

        if phase in mission.skipped_phases:
            for _, task in indexed_tasks:
                mission.log(f"Skipping task '{task.description}' (phase skipped)")
            global_task_counter += len(indexed_tasks)
            continue

        completed_task_ids: set[str] = set()

        independent = [
            (i, t)
            for i, t in indexed_tasks
            if not t.dependencies
            or all(d in completed_task_ids for d in t.dependencies)
        ]
        dependent = [
            (i, t) for i, t in indexed_tasks if (i, t) not in independent
        ]

        if independent:
            async def _run_task(
                idx: int,
                task: Any,
                _context: AgentContext = context,
            ) -> None:
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

                if not executor:
                    raise RuntimeError("Executor not initialized")
                await executor.execute_task(mission, task, _context_copy)

            results = await asyncio.gather(
                *[_run_task(idx, t) for idx, t in independent],
                return_exceptions=True,
            )

            for (idx, task), result in zip(independent, results, strict=False):
                if isinstance(result, Exception):
                    await handle_task_failure(
                        mission, task, str(result), context,
                        mission_controller, consensus, steering,
                    )
                    await lifecycle.update_db_status(mission)
                else:
                    completed_task_ids.add(task.task_id)
                    current_findings = len(mission.findings)
                    new_findings = current_findings - last_findings_count
                    effective_idx = global_task_counter + independent.index(
                        (idx, task)
                    )
                    if (
                        new_findings >= 3
                        and effective_idx > last_adaptation_index + 2
                    ):
                        await adapt_plan_to_findings(
                            mission, context, new_findings,
                            mission_controller, steering,
                        )
                        last_adaptation_index = effective_idx
                        last_findings_count = current_findings
                    await lifecycle.update_db_status(mission)
                    await lifecycle.save_checkpoint(mission)

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
                if not executor:
                    raise RuntimeError("Executor not initialized")
                await executor.execute_task(mission, task, context)
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
                    await adapt_plan_to_findings(
                        mission, context, new_findings,
                        mission_controller, steering,
                    )
                    last_adaptation_index = effective_idx
                    last_findings_count = current_findings

                await lifecycle.update_db_status(mission)
                await lifecycle.save_checkpoint(mission)
            except Exception as e:
                await handle_task_failure(
                    mission, task, str(e), context,
                    mission_controller, consensus, steering,
                )
                await lifecycle.update_db_status(mission)

        global_task_counter += len(indexed_tasks)
