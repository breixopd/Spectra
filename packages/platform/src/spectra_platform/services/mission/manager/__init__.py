"""Mission Manager - high-level orchestration of security missions."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

from spectra_common.constants import MAX_CONCURRENT_MISSIONS
from spectra_platform.services.mission.mission import Mission

from . import execution, lifecycle, steering
from .execution import MissionExecutionManager
from .lifecycle import MissionLifecycleManager
from .steering import MissionSteeringManager

logger = logging.getLogger(__name__)


class MissionManager:
    """
    Singleton manager for security assessment missions.

    Responsibilities:
    - Manage mission lifecycle (start, stop, get)
    - Coordinate the mission execution flow
    - Handle adaptive replanning on failures
    - Apply steering actions

    Delegates to:
    - MissionLifecycleManager: state tracking
    - MissionExecutionManager: task execution
    - MissionSteeringManager: adaptive logic
    """

    def __init__(self):
        self.active_missions: dict[str, Mission] = {}
        self.lifecycle = MissionLifecycleManager(self.active_missions)
        self.steering = MissionSteeringManager(self.active_missions)
        self.execution = MissionExecutionManager(self.lifecycle, self.steering)
        self._agents_initialized = False

        # Concurrent mission isolation
        self._global_semaphore = asyncio.Semaphore(MAX_CONCURRENT_MISSIONS)
        self._mission_llm_semaphores: dict[str, asyncio.Semaphore] = {}

    def _set_mission_llm_semaphore(self, mission_id: str) -> None:
        self._mission_llm_semaphores[mission_id] = asyncio.Semaphore(1)

    def _schedule_mission_task(self, coroutine: Coroutine[Any, Any, None]) -> None:
        from spectra_common.tasks import create_safe_task

        create_safe_task(coroutine, name="mission-task")

    async def _ensure_agents(self) -> None:
        """Initialize agents."""
        if not self._agents_initialized:
            await self.execution.ensure_agents()
            self._agents_initialized = True

    async def _run_mission_with_limit(self, mission: Mission) -> None:
        """Run mission loop within global concurrency semaphore."""
        async with self._global_semaphore:
            await self.execution.run_mission_loop(mission)
        self._mission_llm_semaphores.pop(mission.id, None)

    # --- Public API ---

    async def start_mission(
        self,
        target: str,
        directive: str,
        requirements: str | None = None,
        vpn_config: str | None = None,
        user_id: str | None = None,
        requires_approval: bool = False,
        *,
        record_demo: bool = False,
        playbook_id: str | None = None,
        scan_mode: str = "autonomous",
    ) -> str:
        """
        Start a new security assessment mission.

        Args:
            target: Target IP, domain, or CIDR
            directive: High-level user directive
            requirements: Optional scope, requirements, or constraints
            vpn_config: Optional VPN config name to use for this mission
            user_id: ID of the user who owns this mission

        Returns:
            Mission ID
        """
        await self._ensure_agents()

        mission = await self.lifecycle.start_mission(
            target,
            directive,
            requirements,
            vpn_config=vpn_config,
            user_id=user_id,
            requires_approval=requires_approval,
            record_demo=record_demo,
            playbook_id=playbook_id,
            scan_mode=scan_mode,
        )

        # Create per-mission LLM semaphore (max 1 concurrent LLM call)
        self._set_mission_llm_semaphore(mission.id)

        # Start execution loop in background with global concurrency limit
        self._schedule_mission_task(self._run_mission_with_limit(mission))

        return mission.id

    async def stop_mission(self, mission_id: str) -> bool:
        """Stop a running mission."""
        return await self.lifecycle.stop_mission(mission_id)

    async def pause_mission(self, mission_id: str) -> bool:
        """Pause a running mission."""
        return await self.lifecycle.pause_mission(mission_id)

    async def resume_mission(self, mission_id: str) -> bool:
        """Resume a paused mission."""
        return await self.lifecycle.resume_mission(mission_id)

    async def resume_mission_from_checkpoint(self, mission_id: str) -> str | None:
        """Resume a mission from its DB checkpoint.

        Returns the mission ID on success, None if no checkpoint exists.
        """
        await self._ensure_agents()
        try:
            mission = await self.lifecycle.resume_mission_from_db(mission_id)
        except ValueError:
            return None

        self._schedule_mission_task(self.execution.run_mission_loop(mission))
        return mission.id

    async def get_mission(self, mission_id: str) -> Mission | None:
        """Get mission by ID."""
        return self.lifecycle.get_mission(mission_id)

    async def steer_mission(
        self,
        mission_id: str,
        action: str,
        phase: str | None = None,
        target: str | None = None,
        vulnerability: str | None = None,
        **kwargs: Any,
    ) -> dict[str, str]:
        """
        Steer a running mission.

        Args:
            mission_id: ID of the mission to steer
            action: Steering action (skip_phase, prioritize_target, focus_vuln,
                    inject_task, set_param, set_automation_level, go_back, skip_target)
            phase: Phase to skip (for skip_phase)
            target: Target to prioritize (for prioritize_target)
            vulnerability: Vuln to focus on (for focus_vuln)
            **kwargs: Additional args for extended actions

        Returns:
            Dict with result message

        Raises:
            ValueError: If mission not found or input invalid
        """
        return await self.steering.steer_mission(mission_id, action, phase, target, vulnerability, **kwargs)

    def list_missions(self) -> list[dict[str, Any]]:
        """List all missions with their status."""
        return self.lifecycle.list_missions()


# Global singleton instance
mission_manager = MissionManager()
