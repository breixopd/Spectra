"""Mission steering and adaptation logic."""

from __future__ import annotations

import logging
import uuid

from app.models.attack_surface import AttackVector, VectorPriority
from app.services.ai.agents.base import SteeringAction
from app.services.mission.mission import Mission

logger = logging.getLogger("spectra.mission.manager.steering")


class MissionSteeringManager:
    """Handles mission steering and adaptive flow control."""

    def __init__(self, active_missions: dict[str, Mission]):
        self.active_missions = active_missions

    async def steer_mission(
        self,
        mission_id: str,
        action: str,
        phase: str | None = None,
        target: str | None = None,
        vulnerability: str | None = None,
        task: dict | None = None,
        param_key: str | None = None,
        param_value: str | None = None,
        automation_level: str | None = None,
    ) -> dict[str, str]:
        """
        Steer a running mission.

        Args:
            mission_id: ID of the mission to steer
            action: Steering action (skip_phase, prioritize_target, focus_vuln,
                    inject_task, set_param, set_automation_level, go_back, skip_target)
            phase: Phase to skip or go back to
            target: Target to prioritize or skip
            vulnerability: Vuln to focus on
            task: Task definition to inject
            param_key: Parameter key for set_param
            param_value: Parameter value for set_param
            automation_level: Automation level (full_auto, semi_auto, manual)

        Returns:
            Dict with result message

        Raises:
            ValueError: If mission not found or input invalid
        """
        mission = self.active_missions.get(mission_id)
        if not mission:
            raise ValueError("Mission not found or not active")

        if action == "skip_phase" and phase:
            mission.skipped_phases.add(phase)
            mission.log(f"[STEER] Skipping phase: {phase}")
            return {"message": f"Phase '{phase}' will be skipped"}

        elif action == "prioritize_target" and target:
            # Add to attack surface with high priority
            vector = AttackVector(
                id=str(uuid.uuid4()),
                name=f"Priority: {target}",
                description="Human-prioritized target",
                priority=VectorPriority.CRITICAL,
                target_type="service",
                target_ref=target,
            )
            mission.attack_surface.add_vector(vector)
            mission.log(f"[STEER] Prioritizing target: {target}")
            return {"message": f"Target '{target}' prioritized"}

        elif action == "focus_vuln" and vulnerability:
            mission.log(f"[STEER] Focusing on vulnerability: {vulnerability}")
            return {"message": f"Focusing on vulnerability: {vulnerability}"}

        elif action == "inject_task" and task:
            if not mission.plan:
                raise ValueError("No plan exists to inject tasks into")
            from app.services.ai.agents.mission_controller import Task, AssessmentPhase
            new_task = Task(
                task_id=str(uuid.uuid4()),
                phase=AssessmentPhase(task.get("phase", "discovery")),
                description=task.get("description", "Injected task"),
                agent_type=task.get("agent_type", "tool_selector"),
                priority=task.get("priority", 5),
            )
            insert_idx = mission.current_task_index + 1
            mission.plan.tasks.insert(insert_idx, new_task)
            mission.log(f"[STEER] Injected task: {new_task.description}")
            return {"message": f"Task '{new_task.description}' injected at position {insert_idx}"}

        elif action == "set_param" and param_key and param_value is not None:
            if not hasattr(mission, "steering_params"):
                mission.steering_params = {}
            mission.steering_params[param_key] = param_value
            mission.log(f"[STEER] Set parameter: {param_key}={param_value}")
            return {"message": f"Parameter '{param_key}' set to '{param_value}'"}

        elif action == "set_automation_level" and automation_level:
            valid_levels = ("full_auto", "semi_auto", "manual")
            if automation_level not in valid_levels:
                raise ValueError(f"Invalid automation level. Choose from: {valid_levels}")
            mission.automation_level = automation_level
            mission.log(f"[STEER] Automation level set to: {automation_level}")
            return {"message": f"Automation level set to '{automation_level}'"}

        elif action == "go_back" and phase:
            if not mission.plan:
                raise ValueError("No plan exists to navigate")
            # Remove phase from skipped if it was skipped
            mission.skipped_phases.discard(phase)
            # Find first task of the requested phase
            for i, t in enumerate(mission.plan.tasks):
                if t.phase.value == phase:
                    mission.current_task_index = max(0, i - 1)
                    mission.log(f"[STEER] Going back to phase: {phase} (task {i})")
                    return {"message": f"Returned to phase '{phase}'"}
            raise ValueError(f"Phase '{phase}' not found in plan")

        elif action == "skip_target" and target:
            mission.log(f"[STEER] Skipping target: {target}")
            if not hasattr(mission, "skipped_targets"):
                mission.skipped_targets = set()
            mission.skipped_targets.add(target)
            return {"message": f"Target '{target}' will be skipped"}

        else:
            raise ValueError(
                f"Invalid action '{action}' or missing required parameters"
            )

    async def apply_steering_action(
        self, mission: Mission, action: SteeringAction
    ) -> None:
        """Apply a steering action to modify mission flow."""
        mission.log(f"[STEERING] Applying: {action.reasoning}")

        # Skip phases
        if hasattr(action, "skip_phases") and action.skip_phases:
            mission.log(f"[STEERING] Skipping phases: {action.skip_phases}")
            for phase in action.skip_phases:
                mission.skipped_phases.add(phase)

        # Prioritize targets
        if hasattr(action, "priority_targets") and action.priority_targets:
            mission.log(f"[STEERING] Prioritizing: {action.priority_targets}")
            mission.attack_surface.prioritize_vectors(action.priority_targets)

        # Phase transition
        if (
            hasattr(action, "new_phase")
            and mission.plan
            and action.new_phase != mission.plan.current_phase
        ):
            mission.log(f"[STEERING] Transitioning to phase: {action.new_phase}")

            # Find first task of new phase
            found_index = -1
            for i, task in enumerate(mission.plan.tasks):
                if task.phase.value == action.new_phase:
                    found_index = i
                    break

            if found_index != -1:
                mission.log(f"[STEERING] Jumping to task {found_index}")

                # Mark intermediate phases as skipped
                for i in range(mission.current_task_index + 1, found_index):
                    phase = mission.plan.tasks[i].phase.value
                    if phase != action.new_phase:
                        mission.skipped_phases.add(phase)
                        mission.log(f"[STEERING] Marking phase {phase} as skipped")
            else:
                mission.log(f"[STEERING] No task found for phase {action.new_phase}")

        # Stop mission
        if hasattr(action, "new_phase") and action.new_phase == "complete":
            mission.stop()
