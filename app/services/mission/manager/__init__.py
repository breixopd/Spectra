"""Mission Manager - high-level orchestration of security missions."""

from __future__ import annotations

import logging
from typing import Any

from app.services.mission.mission import Mission
from . import lifecycle, steering, execution
from .lifecycle import MissionLifecycleManager
from .steering import MissionSteeringManager
from .execution import MissionExecutionManager

logger = logging.getLogger("spectra.mission.manager")


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

    async def _ensure_agents(self) -> None:
        """Initialize agents."""
        if not self._agents_initialized:
            await self.execution.ensure_agents()
            self._agents_initialized = True

    # --- Public API ---

    async def start_mission(self, target: str, directive: str) -> str:
        """
        Start a new security assessment mission.

        Args:
            target: Target IP, domain, or CIDR
            directive: High-level user directive

        Returns:
            Mission ID
        """
        await self._ensure_agents()

        mission = await self.lifecycle.start_mission(target, directive)

        # Start execution loop in background
        import asyncio

        asyncio.create_task(self.execution.run_mission_loop(mission))

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
        return await self.steering.steer_mission(
            mission_id, action, phase, target, vulnerability
        )

    def list_missions(self) -> list[dict[str, Any]]:
        """List all missions with their status."""
        return self.lifecycle.list_missions()


# Global singleton instance
mission_manager = MissionManager()
