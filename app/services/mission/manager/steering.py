"""Mission steering and adaptation logic."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.core.events import events
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
    ) -> dict[str, str]:
        """
        Steer a running mission.

        Args:
            mission_id: ID of the mission to steer
            action: Steering action (skip_phase, prioritize_target, focus_vuln)
            phase: Phase to skip (for skip_phase)
            target: Target to prioritize (for prioritize_target)
            vulnerability: Vuln to focus on (for focus_vuln)

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
