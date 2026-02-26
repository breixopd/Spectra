"""Mission lifecycle management."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.core.database import async_session_maker
from app.core.events import events
from app.repositories.mission import MissionRepository
from app.services.ai.agents.base import AgentContext
from app.services.mission.mission import Mission
from app.utils.geoip import resolve_ip

logger = logging.getLogger("spectra.mission.manager.lifecycle")


class MissionLifecycleManager:
    """Manages creation, state changes, and persistence of missions."""

    def __init__(self, active_missions: dict[str, Mission]):
        self.active_missions = active_missions

    async def start_mission(self, target: str, directive: str) -> Mission:
        """Create and start a new mission."""
        mission = Mission(target, directive)
        self.active_missions[mission.id] = mission

        # Persist to DB
        try:
            async with async_session_maker() as session:
                async with session.begin():
                    repo = MissionRepository(session)
                    await repo.create(
                        id=mission.id,
                        target=target,
                        directive=directive,
                        status="created",
                        logs=[],
                        summary={},
                    )
        except SQLAlchemyError as e:
            logger.error("Failed to persist mission start (DB error): %s", e)
        except Exception as e:
            logger.error("Failed to persist mission start (Unexpected): %s", e)

        return mission

    async def stop_mission(self, mission_id: str) -> bool:
        """Stop a running mission."""
        if mission_id in self.active_missions:
            self.active_missions[mission_id].stop()
            # Update DB status immediately
            await self.update_db_status(self.active_missions[mission_id])
            return True
        return False

    async def pause_mission(self, mission_id: str) -> bool:
        """Pause a running mission."""
        if mission_id in self.active_missions:
            self.active_missions[mission_id].pause()
            await self.update_db_status(self.active_missions[mission_id])
            return True
        return False

    async def resume_mission(self, mission_id: str) -> bool:
        """Resume a paused mission."""
        if mission_id in self.active_missions:
            self.active_missions[mission_id].resume()
            await self.update_db_status(self.active_missions[mission_id])
            return True
        return False

    def get_mission(self, mission_id: str) -> Mission | None:
        """Get mission by ID."""
        return self.active_missions.get(mission_id)

    def list_missions(self) -> list[dict[str, Any]]:
        """List all missions with their status."""
        return [m.to_dict() for m in self.active_missions.values()]

    async def update_db_status(self, mission: Mission) -> None:
        """Update mission status in database."""
        try:
            async with async_session_maker() as session:
                async with session.begin():
                    repo = MissionRepository(session)
                    await repo.update(
                        mission.id,
                        status=mission.status,
                        logs=mission.logs,
                        summary=mission.to_dict(),
                        attack_surface=mission.attack_surface.model_dump(),
                    )
        except SQLAlchemyError as e:
            logger.error("Failed to update mission DB (DB error): %s", e)
        except Exception as e:
            logger.error("Failed to update mission DB (Unexpected): %s", e)

    async def initialize_mission(self, mission: Mission) -> AgentContext | None:
        """Initialize mission and return context."""
        try:
            mission.set_status("running")
            mission.log(f"Starting mission against {mission.target}")
            self._broadcast_state(
                mission.id, "mission_controller", "running", plan="Initializing..."
            )

            # Resolve GeoIP
            mission.log("Resolving target location...")
            geo = await resolve_ip(mission.target)
            if geo:
                mission.geo_info = geo
                mission.log(
                    f"Target located in {geo.get('city')}, {geo.get('country')}"
                )
                mission._broadcast("geo", geo)

            return AgentContext(
                mission_id=mission.id,
                session_id=mission.id,
                target=mission.target,
                mission=mission.directive,
                phase="scope",
                stealth_mode=False,
                max_concurrency=3,
            )

        except Exception as e:
            mission.set_status("failed")
            mission.log(f"Initialization failed: {e}")
            logger.error("Mission init error for %s: %s", mission.id, e, exc_info=True)
            self._broadcast_state(mission.id, "mission_controller", "failed")
            await self.update_db_status(mission)
            return None

    def _broadcast_state(
        self, mission_id: str, agent_id: str, status: str, **kwargs
    ) -> None:
        """Broadcast agent state."""
        # Using events to broadcast. Note: original used self._broadcast which uses events.emit_sync
        # We need to make sure we keep the same signature/behavior.
        # Original: events.emit_sync(msg_type, "mission_manager", **data)
        data = {"agent_id": agent_id, "status": status, **kwargs}
        events.emit_sync("agent_state", "mission_manager", **data)
