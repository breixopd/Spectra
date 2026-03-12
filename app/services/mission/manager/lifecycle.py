"""Mission lifecycle management."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.core.database import async_session_maker
from app.core.events import events
from app.repositories.mission import MissionRepository
from app.services.ai.agents.base import AgentContext
from app.services.billing.quota_enforcer import QuotaEnforcer
from app.services.mission.mission import Mission
from app.services.mission.state_store import MissionStateStore
from app.utils.geoip import resolve_ip

logger = logging.getLogger("spectra.mission.manager.lifecycle")


class MissionQuotaExceeded(Exception):
    """Raised when a user exceeds their plan's mission quota."""


class MissionLifecycleManager:
    """Manages creation, state changes, and persistence of missions."""

    def __init__(self, active_missions: dict[str, Mission]):
        self.active_missions = active_missions
        self.state_store = MissionStateStore()
        self.quota_enforcer = QuotaEnforcer()

    async def start_mission(
        self,
        target: str,
        directive: str,
        requirements: str | None = None,
        vpn_config: str | None = None,
        user_id: str | None = None,
    ) -> Mission:
        """Create and start a new mission."""
        # Enforce mission quota if user is known
        if user_id:
            allowed, reason = await self.quota_enforcer.check_mission_quota(user_id)
            if not allowed:
                raise MissionQuotaExceeded(reason)

        mission = Mission(target, directive, requirements=requirements, vpn_config=vpn_config, user_id=user_id)
        self.active_missions[mission.id] = mission

        # Persist to distributed state store
        await self.state_store.register(mission.id, {
            "id": mission.id,
            "target": target,
            "directive": directive,
            "status": "created",
            "user_id": user_id,
            "started_at": mission.start_time.isoformat(),
        })

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
                        vpn_config=vpn_config,
                        user_id=user_id,
                    )
        except SQLAlchemyError as e:
            logger.error("Failed to persist mission start (DB error): %s", e)
        except Exception as e:
            logger.error("Failed to persist mission start (Unexpected): %s", e)

        return mission

    async def stop_mission(self, mission_id: str) -> bool:
        """Stop a running mission."""
        if mission_id in self.active_missions:
            mission = self.active_missions[mission_id]
            # Disconnect VPN if configured
            if getattr(mission, "vpn_config", None):
                try:
                    from app.services.tools.vpn import VPNManager

                    vpn_mgr = VPNManager()
                    await vpn_mgr.disconnect(mission.vpn_config)
                    logger.info("VPN disconnected for stopped mission %s", mission_id)
                except Exception as e:
                    logger.error("Failed to disconnect VPN for mission %s: %s", mission_id, e)
            mission.stop()
            # Update DB status immediately
            await self.update_db_status(mission)
            # Remove from distributed state
            await self.state_store.unregister(mission_id)
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

        # Sync to distributed state store
        try:
            await self.state_store.update_state(mission.id, {
                "id": mission.id,
                "target": mission.target,
                "directive": mission.directive,
                "status": mission.status,
                "user_id": mission.user_id,
                "started_at": mission.start_time.isoformat(),
            })
        except Exception as e:
            logger.warning("Failed to sync mission state to store: %s", e)

    async def save_checkpoint(self, mission: Mission) -> None:
        """Save mission checkpoint state to DB."""
        try:
            checkpoint = mission.save_checkpoint()
            async with async_session_maker() as session:
                async with session.begin():
                    repo = MissionRepository(session)
                    await repo.update(
                        mission.id,
                        checkpoint_data=checkpoint,
                        resume=True,
                    )
            logger.info("Checkpoint saved for mission %s", mission.id)
        except Exception as e:
            logger.error("Failed to save checkpoint for mission %s: %s", mission.id, e)

    async def resume_mission_from_db(self, mission_id: str) -> Mission | None:
        """Reconstruct a mission from checkpoint data stored in DB."""
        try:
            async with async_session_maker() as session:
                async with session.begin():
                    repo = MissionRepository(session)
                    db_mission = await repo.get(mission_id)
                    if not db_mission or not db_mission.checkpoint_data:
                        logger.warning("No checkpoint data for mission %s", mission_id)
                        return None

                    mission = Mission.from_checkpoint(db_mission.checkpoint_data)
                    self.active_missions[mission.id] = mission
                    mission.log("[RESUME] Mission resumed from checkpoint")
                    return mission
        except Exception as e:
            logger.error("Failed to resume mission %s: %s", mission_id, e)
            return None

    async def initialize_mission(self, mission: Mission) -> AgentContext | None:
        """Initialize mission and return context."""
        try:
            mission.set_status("running")
            mission.log(f"Starting mission against {mission.target}")

            # Connect per-mission VPN if configured
            if mission.vpn_config:
                try:
                    from app.services.tools.vpn import VPNManager

                    vpn_mgr = VPNManager()
                    result = await vpn_mgr.connect(mission.vpn_config)
                    mission.log(f"[VPN] Connected via '{mission.vpn_config}' (job: {result.get('job_id', 'N/A')})")
                    # Wait for VPN tunnel to establish
                    job_id = result.get("job_id")
                    if job_id:
                        try:
                            from app.core.queue import Job

                            job = Job(job_id)
                            await job.result(timeout=30)
                            mission.log("[VPN] Tunnel established successfully")
                        except Exception:
                            mission.log("[VPN] Warning: tunnel not confirmed after 30s, proceeding anyway")
                            logger.warning("VPN tunnel not confirmed for mission %s after 30s", mission.id)
                except Exception as vpn_err:
                    mission.log(f"[VPN] Failed to connect '{mission.vpn_config}': {vpn_err}")
                    logger.error("VPN connect failed for mission %s: %s", mission.id, vpn_err)
            else:
                # Log VPN status
                try:
                    from app.services.tools.vpn import VPNManager

                    vpn_mgr = VPNManager()
                    configs = await vpn_mgr.list_configs()
                    if configs:
                        mission.log(f"[VPN] {len(configs)} VPN config(s) available")
                    else:
                        mission.log("[VPN] No VPN connection active - using direct network")
                except Exception:
                    mission.log("[VPN] Could not check VPN status")

            self._broadcast_state(mission.id, "mission_controller", "running", plan="Initializing...")

            # Resolve GeoIP
            mission.log("Resolving target location...")
            geo = await resolve_ip(mission.target)
            if geo:
                mission.geo_info = geo
                mission.log(f"Target located in {geo.get('city')}, {geo.get('country')}")
                mission._broadcast("geo", geo)

            effective_mission = mission.directive
            if mission.requirements:
                effective_mission = f"{mission.directive}\n\nRequirements:\n{mission.requirements}"

            return AgentContext(
                mission_id=mission.id,
                session_id=mission.id,
                target=mission.target,
                mission=effective_mission,
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

    def _broadcast_state(self, mission_id: str, agent_id: str, status: str, **kwargs) -> None:
        """Broadcast agent state."""
        # Using events to broadcast. Note: original used self._broadcast which uses events.emit_sync
        # We need to make sure we keep the same signature/behavior.
        # Original: events.emit_sync(msg_type, "mission_manager", **data)
        data = {"agent_id": agent_id, "status": status, **kwargs}
        events.emit_sync("agent_state", "mission_manager", **data)
