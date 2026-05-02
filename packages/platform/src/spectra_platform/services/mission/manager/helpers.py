"""Mission execution helper functions: debrief, reporting, plan adaptation, task execution."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from spectra_common.constants import (
    DEBRIEF_MAX_FINDINGS,
    DEBRIEF_MAX_LOGS,
    DEBRIEF_SUMMARY_LOG_CHARS,
    MISSION_TIMEOUT_SECONDS,
)
from spectra_platform.services.ai.agents.base import AgentContext, SteeringAction
from spectra_platform.services.ai.agents.mission_controller import (
    MissionInput,
    MissionPlan,
)
from spectra_platform.services.ai.consensus import QualityGate, VotingSystem

if TYPE_CHECKING:
    from spectra_platform.services.ai.agents.mission_controller import MissionController
    from spectra_platform.services.mission.executor import MissionExecutor
    from spectra_platform.services.mission.manager.lifecycle import MissionLifecycleManager
    from spectra_platform.services.mission.manager.steering import MissionSteeringManager
    from spectra_platform.services.mission.mission import Mission

logger = logging.getLogger(__name__)


async def run_debrief(
    mission: Mission,
    context: AgentContext,
    mission_controller: MissionController | None,
) -> None:
    """Run AI debrief analysis after mission completion."""
    try:
        from spectra_platform.services.ai.agents.debrief import DebriefAgent, DebriefInput

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
            mission.log(f"[DEBRIEF] {action.executive_summary[:DEBRIEF_SUMMARY_LOG_CHARS]}")
            for lesson in action.lessons_learned[:3]:
                mission.log(f"[LEARN] {lesson}")

            try:
                from spectra_platform.services.ai.feedback import send_quality_score

                inference_id = getattr(debrief, "_last_inference_id", "")
                lesson_score = min(len(action.lessons_learned), 3) / 3
                summary_score = 1.0 if action.executive_summary else 0.0
                await send_quality_score(inference_id, round((lesson_score + summary_score) / 2, 2))
            except (OSError, RuntimeError, ValueError, TypeError):
                logger.debug("Failed to send debrief quality feedback (non-critical)")

            try:
                from spectra_platform.services.ai.memory import get_memory

                memory = get_memory(mission.user_id)
                for lesson in action.lessons_learned[:5]:
                    memory.record_tool_lesson(
                        tool="debrief",
                        lesson=lesson,
                        context=f"Mission {mission.id} against {mission.target}",
                    )
            except (OSError, RuntimeError):
                logger.debug("Failed to persist debrief lessons (non-critical)")
    except (OSError, RuntimeError, ValueError) as e:
        logger.debug("Debrief failed (non-critical): %s", e)


async def generate_html_report(mission: Mission) -> None:
    """Generate HTML report from mission data."""
    try:
        from spectra_platform.services.mission.report_generator import (
            generate_html_report as _gen,
        )
        from spectra_platform.services.mission.report_generator import (
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
    except (OSError, RuntimeError, ValueError, TypeError, AttributeError) as e:
        logger.warning("HTML report generation failed: %s", e)


async def adapt_plan_to_findings(
    mission: Mission,
    context: AgentContext,
    new_findings_count: int,
    mission_controller: MissionController | None,
    steering: MissionSteeringManager,
) -> None:
    """Adapt mission plan based on new findings (PTES/MAKER methodology)."""
    mission.log(f"[ADAPT] {new_findings_count} new findings discovered. Evaluating plan adaptation...")

    try:
        recent_findings = mission.findings[-new_findings_count:]
        critical_high = [f for f in recent_findings if str(f.get("severity", "")).lower() in ("critical", "high")]

        if not critical_high:
            mission.log("[ADAPT] No critical/high findings - continuing with current plan")
            return

        finding_summary = "; ".join(
            [f"{f.get('title', 'Unknown')} ({f.get('severity', 'unknown')})" for f in critical_high[:5]]
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
                    mission.log(f"[ADAPT] Added {len(new_tasks[:5])} new tasks to plan")
        else:
            mission.log("[ADAPT] Plan adaptation not needed")

    except (OSError, RuntimeError, ValueError) as e:
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
                    mission.log(f"[REJECTED] Replan rejected: {vote_result.escalation_reason}")
                    mission.log("[ADAPT] Continuing with original plan")
                    return

                mission.log("[APPROVED] Replan validated")
                await steering.apply_steering_action(mission, result.action)
            else:
                mission.log("[ADAPT] Unexpected action type from controller")
        else:
            mission.log(f"[ADAPT] Replanning failed: {result.error}")

    except (OSError, RuntimeError, ValueError) as e:
        logger.error("Adaptive replanning failed: %s", e, exc_info=True)
        mission.log(f"[ADAPT] Critical failure: {e}")


def _group_tasks_by_phase(tasks: list[Any]) -> dict[str, list[tuple[int, Any]]]:
    """Preserve plan order while grouping tasks under each phase."""
    phase_groups: dict[str, list[tuple[int, Any]]] = {}
    for index, task in enumerate(tasks):
        phase_groups.setdefault(task.phase.value, []).append((index, task))
    return phase_groups


def _partition_phase_tasks(
    indexed_tasks: list[tuple[int, Any]],
    completed_task_ids: set[str],
) -> tuple[list[tuple[int, Any]], list[tuple[int, Any]]]:
    independent = [
        (index, task)
        for index, task in indexed_tasks
        if not task.dependencies or all(dependency in completed_task_ids for dependency in task.dependencies)
    ]
    dependent = [(index, task) for index, task in indexed_tasks if (index, task) not in independent]
    return independent, dependent


def _should_run_adaptation(
    new_findings_count: int,
    effective_index: int,
    last_adaptation_index: int,
) -> bool:
    return new_findings_count >= 3 and effective_index > last_adaptation_index + 2


def _copy_task_context(context: AgentContext, phase: str) -> AgentContext:
    task_context = AgentContext(
        mission_id=context.mission_id,
        session_id=context.session_id,
        user_id=context.user_id,
        user_role=context.user_role,
        plan_features=context.plan_features,
        tenant_quotas=context.tenant_quotas,
        target=context.target,
        mission=context.mission,
        phase=phase,
    )
    return task_context


def _log_task_start(mission: Mission, index: int, task: Any) -> None:
    mission.current_task_index = index
    total = len(mission.plan.tasks) if mission.plan else 0
    mission.log(f"[TASK] Executing task [{index + 1}/{total}]: {task.description}")


def _require_executor(executor: MissionExecutor | None) -> MissionExecutor:
    if not executor:
        raise RuntimeError("Executor not initialized")
    return executor


def _mission_stop_requested(mission: Mission) -> bool:
    if not mission.is_stopped():
        return False
    mission.log("Mission stopped by user")
    return True


def _mission_timed_out(mission: Mission) -> bool:
    elapsed = time.time() - getattr(mission, "_start_wall_time", time.time())
    if elapsed <= MISSION_TIMEOUT_SECONDS:
        return False
    mission.log(f"[TIMEOUT] Mission timed out after {int(elapsed)}s (limit: {MISSION_TIMEOUT_SECONDS}s)")
    mission.set_status("timed_out")
    return True


def _task_execution_context(
    context: AgentContext,
    task: Any,
    *,
    copy_context: bool,
) -> AgentContext:
    if copy_context:
        return _copy_task_context(context, task.phase.value)
    context.phase = task.phase.value
    return context


async def _execute_task(
    mission: Mission,
    executor: MissionExecutor | None,
    index: int,
    task: Any,
    context: AgentContext,
    *,
    copy_context: bool,
) -> None:
    _log_task_start(mission, index, task)
    task_context = _task_execution_context(
        context,
        task,
        copy_context=copy_context,
    )
    await _require_executor(executor).execute_task(mission, task, task_context)


async def _handle_successful_task(
    mission: Mission,
    context: AgentContext,
    mission_controller: MissionController | None,
    steering: MissionSteeringManager,
    lifecycle: MissionLifecycleManager,
    last_findings_count: int,
    last_adaptation_index: int,
    effective_index: int,
) -> tuple[int, int]:
    current_findings = len(mission.findings)
    new_findings = current_findings - last_findings_count

    if _should_run_adaptation(
        new_findings,
        effective_index,
        last_adaptation_index,
    ):
        await adapt_plan_to_findings(
            mission,
            context,
            new_findings,
            mission_controller,
            steering,
        )
        last_adaptation_index = effective_index
        last_findings_count = current_findings

    await lifecycle.update_db_status(mission)
    await lifecycle.save_checkpoint(mission)
    return last_findings_count, last_adaptation_index


async def _handle_task_execution_result(
    mission: Mission,
    task: Any,
    result: Exception | None,
    context: AgentContext,
    mission_controller: MissionController | None,
    consensus: VotingSystem | None,
    steering: MissionSteeringManager,
    lifecycle: MissionLifecycleManager,
    completed_task_ids: set[str],
    last_findings_count: int,
    last_adaptation_index: int,
    effective_index: int,
) -> tuple[int, int]:
    if result is not None:
        await handle_task_failure(
            mission,
            task,
            str(result),
            context,
            mission_controller,
            consensus,
            steering,
        )
        await lifecycle.update_db_status(mission)
        return last_findings_count, last_adaptation_index

    completed_task_ids.add(task.task_id)
    return await _handle_successful_task(
        mission,
        context,
        mission_controller,
        steering,
        lifecycle,
        last_findings_count,
        last_adaptation_index,
        effective_index,
    )


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
    phase_groups = _group_tasks_by_phase(mission.plan.tasks)

    global_task_counter = 0

    for phase, indexed_tasks in phase_groups.items():
        if _mission_stop_requested(mission):
            break

        if _mission_timed_out(mission):
            break

        await mission.wait_if_paused()

        if phase in mission.skipped_phases:
            for _, task in indexed_tasks:
                mission.log(f"Skipping task '{task.description}' (phase skipped)")
            global_task_counter += len(indexed_tasks)
            continue

        completed_task_ids: set[str] = set()
        independent, dependent = _partition_phase_tasks(
            indexed_tasks,
            completed_task_ids,
        )

        if independent:

            async def _run_task(
                idx: int,
                task: Any,
                _context: AgentContext = context,
            ) -> None:
                await _execute_task(
                    mission,
                    executor,
                    idx,
                    task,
                    _context,
                    copy_context=True,
                )

            results = await asyncio.gather(
                *[_run_task(idx, t) for idx, t in independent],
                return_exceptions=True,
            )

            for position, ((_, task), result) in enumerate(zip(independent, results, strict=False)):
                task_result = result if isinstance(result, Exception) else None
                effective_idx = global_task_counter + position
                last_findings_count, last_adaptation_index = await _handle_task_execution_result(
                    mission,
                    task,
                    task_result,
                    context,
                    mission_controller,
                    consensus,
                    steering,
                    lifecycle,
                    completed_task_ids,
                    last_findings_count,
                    last_adaptation_index,
                    effective_idx,
                )

        for position, (idx, task) in enumerate(dependent):
            if _mission_stop_requested(mission):
                break

            await mission.wait_if_paused()
            effective_idx = global_task_counter + len(independent) + position

            try:
                await _execute_task(
                    mission,
                    executor,
                    idx,
                    task,
                    context,
                    copy_context=False,
                )
            except (OSError, RuntimeError, ValueError) as e:
                result: Exception | None = e
            else:
                result = None

            last_findings_count, last_adaptation_index = await _handle_task_execution_result(
                mission,
                task,
                result,
                context,
                mission_controller,
                consensus,
                steering,
                lifecycle,
                completed_task_ids,
                last_findings_count,
                last_adaptation_index,
                effective_idx,
            )

        global_task_counter += len(indexed_tasks)
