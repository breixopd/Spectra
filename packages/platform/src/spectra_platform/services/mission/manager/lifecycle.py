"""Mission lifecycle management."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from spectra_ai.sanitizer import sanitize_for_prompt
from spectra_common.advisory_locks import stable_lock_id
from spectra_platform.core.database import async_session_maker
from spectra_platform.infrastructure.events import EventType, events
from spectra_platform.models.mission import Mission as MissionModel
from spectra_platform.models.user import User
from spectra_platform.repositories.mission import MissionRepository
from spectra_platform.services.ai.agents.base import AgentContext
from spectra_platform.services.billing.entitlements import get_user_entitlement_plan
from spectra_platform.services.billing.quota_enforcer import QuotaEnforcer
from spectra_platform.services.billing.usage_tracker import UsageTracker
from spectra_platform.services.mission.framework_progress import normalize_pentest_framework
from spectra_platform.services.mission.mission import Mission
from spectra_platform.services.mission.state_store import MissionStateStore
from spectra_platform.services.tools.output import cleanup_mission_workspace
from spectra_platform.services.training.dataset import create_mission_completion_sample
from spectra_platform.utils.geoip import resolve_ip

logger = logging.getLogger(__name__)


def _directive_with_playbook(playbook_id: str | None, directive: str) -> str:
    """Prefix directive when an adversary playbook is selected (catalog id)."""
    if not playbook_id or not directive:
        return directive
    from spectra_platform.services.ai.adversary_playbooks import get_adversary_playbook

    pb = get_adversary_playbook(playbook_id)
    if pb is None:
        return directive
    return f"[Adversary playbook: {pb.name} — {pb.threat_actor}] {directive}"


async def _load_capability_context(user_id: str | None) -> tuple[str | None, dict[str, Any], dict[str, Any]]:
    if not user_id:
        return None, {}, {}
    try:
        async with async_session_maker() as db:
            user = await db.scalar(select(User).where(User.id == user_id))
            plan = await get_user_entitlement_plan(db, user_id)
            quotas = {}
            if plan:
                quotas = {
                    "max_concurrent_missions": plan.max_concurrent_missions,
                    "sandbox_resource_tier": plan.sandbox_resource_tier,
                    "sandbox_max_containers": plan.sandbox_max_containers,
                }
            return getattr(user, "role", None), dict(plan.features or {}) if plan else {}, quotas
    except Exception as exc:
        logger.warning("Failed to load capability context for user %s: %s", user_id, exc)
        return None, {}, {}


class MissionQuotaExceeded(Exception):
    """Raised when a user exceeds their plan's mission quota."""


class MissionLifecycleManager:
    """Manages creation, state changes, and persistence of missions."""

    def __init__(self, active_missions: dict[str, Mission]):
        self.active_missions = active_missions
        self.state_store = MissionStateStore()
        self.quota_enforcer = QuotaEnforcer()
        self.usage_tracker = UsageTracker()

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
        pentest_framework: str = "ptes",
    ) -> Mission:
        """Create and start a new mission."""
        effective_directive = _directive_with_playbook(playbook_id, directive)
        fw = normalize_pentest_framework(pentest_framework)
        mission = Mission(
            target,
            effective_directive,
            requirements=requirements,
            vpn_config=vpn_config,
            user_id=user_id,
            requires_approval=requires_approval,
            record_demo=record_demo,
            playbook_id=playbook_id,
            scan_mode=scan_mode,
            pentest_framework=fw,
        )

        # Persist to DB — quota check + row creation run inside one
        # transaction under a per-user advisory lock so two concurrent
        # requests cannot both pass the quota check (TOCTOU fix).
        try:
            async with async_session_maker() as session, session.begin():
                if user_id:
                    lock_id = stable_lock_id(f"spectra_mission_quota:{user_id}")
                    await session.execute(
                        text("SELECT pg_advisory_xact_lock(:lock_id)"),
                        {"lock_id": lock_id},
                    )
                    allowed, reason = await self.quota_enforcer.check_mission_quota(
                        user_id, session=session,
                    )
                    if not allowed:
                        raise MissionQuotaExceeded(reason)

                repo = MissionRepository(session)
                await repo.create(
                    id=mission.id,
                    target=target,
                    directive=effective_directive,
                    status="created",
                    logs=[],
                    summary={"pentest_framework": fw},
                    vpn_config=vpn_config,
                    user_id=user_id,
                    requires_approval=requires_approval,
                    playbook_id=playbook_id,
                    record_demo=record_demo,
                    scan_mode=scan_mode,
                )
                if user_id:
                    await self.usage_tracker.record_mission_start(user_id, session=session)
        except MissionQuotaExceeded:
            raise
        except SQLAlchemyError as e:
            logger.error("Failed to persist mission start (DB error): %s", e)
            raise RuntimeError("Mission could not be persisted") from e
        except (OSError, RuntimeError, TypeError, AttributeError) as e:
            logger.error("Failed to persist mission start (Unexpected): %s", e)
            raise RuntimeError("Mission could not be persisted") from e

        self.active_missions[mission.id] = mission

        # Persist to distributed state store
        await self.state_store.register(
            mission.id,
            {
                "id": mission.id,
                "target": target,
                "directive": effective_directive,
                "status": "created",
                "user_id": user_id,
                "started_at": mission.start_time.isoformat(),
            },
        )

        return mission

    async def stop_mission(self, mission_id: str) -> bool:
        """Stop a running mission."""
        if mission_id in self.active_missions:
            mission = self.active_missions[mission_id]
            try:
                from spectra_platform.services.tools.sandbox import get_sandbox_pool

                pool = get_sandbox_pool()
                if pool and pool.available:
                    await pool.destroy(mission_id)
                    logger.info("Sandbox destroyed for stopped mission %s", mission_id)
            except (ImportError, OSError, RuntimeError) as e:
                logger.error("Failed to destroy sandbox for mission %s: %s", mission_id, e)
            # Disconnect VPN if configured
            if getattr(mission, "vpn_config", None):
                try:
                    from spectra_platform.services.tools.vpn import VPNManager

                    vpn_mgr = VPNManager()
                    await vpn_mgr.disconnect(str(mission.vpn_config))
                    logger.info("VPN disconnected for stopped mission %s", mission_id)
                except (OSError, RuntimeError, ImportError, ValueError, TypeError) as e:
                    logger.error("Failed to disconnect VPN for mission %s: %s", mission_id, e)
            mission.stop()
            # Update DB status immediately
            await self.update_db_status(mission)
            # Remove from distributed state
            await self.state_store.unregister(mission_id)
            cleanup_mission_workspace(mission_id)
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
            async with async_session_maker() as session, session.begin():
                repo = MissionRepository(session)
                mission_summary = mission.to_dict()
                await repo.update(
                    mission.id,
                    status=mission.status,
                    logs=mission.logs,
                    # Mission.summary is the persisted authoritative mission-output read model for API, report, and notification consumers.
                    summary=mission_summary,
                    attack_surface=mission.attack_surface.model_dump(),
                )
                if mission.status == "completed":
                    db_mission = await session.get(MissionModel, mission.id)
                    if db_mission:
                        try:
                            await create_mission_completion_sample(session, db_mission, mission_summary)
                        except Exception:
                            logger.exception("Failed to capture training sample for mission %s", mission.id)
        except SQLAlchemyError as e:
            logger.error("Failed to update mission DB (DB error): %s", e)
        except (OSError, RuntimeError, TypeError, AttributeError) as e:
            logger.error("Failed to update mission DB (Unexpected): %s", e)

        # Sync to distributed state store
        try:
            await self.state_store.update_state(
                mission.id,
                {
                    "id": mission.id,
                    "target": mission.target,
                    "directive": mission.directive,
                    "status": mission.status,
                    "user_id": mission.user_id,
                    "started_at": mission.start_time.isoformat(),
                },
            )
        except (OSError, RuntimeError) as e:
            logger.warning("Failed to sync mission state to store: %s", e)

    async def save_checkpoint(self, mission: Mission) -> None:
        """Save mission checkpoint state to DB."""
        try:
            checkpoint = mission.save_checkpoint()
            async with async_session_maker() as session, session.begin():
                repo = MissionRepository(session)
                await repo.update(
                    mission.id,
                    checkpoint_data=checkpoint,
                    resume=True,
                )
            logger.info("Checkpoint saved for mission %s", mission.id)
        except (OSError, RuntimeError) as e:
            logger.error("Failed to save checkpoint for mission %s: %s", mission.id, e)

    async def resume_mission_from_db(self, mission_id: str) -> Mission:
        """Reconstruct a mission from checkpoint data stored in DB.

        Raises:
            ValueError: If no checkpoint data exists for the mission.
            RuntimeError: If checkpoint deserialization fails.
        """
        try:
            async with async_session_maker() as session, session.begin():
                repo = MissionRepository(session)
                db_mission = await repo.get_by_id(mission_id)
                if not db_mission or not db_mission.checkpoint_data:
                    raise ValueError(f"No checkpoint data for mission {mission_id}")

                mission = Mission.from_checkpoint(db_mission.checkpoint_data)
                self.active_missions[mission.id] = mission
                mission.log("[RESUME] Mission resumed from checkpoint")
                return mission
        except ValueError:
            raise
        except (OSError, RuntimeError) as e:
            raise RuntimeError(f"Failed to resume mission {mission_id}: {e}") from e

    async def initialize_mission(self, mission: Mission) -> AgentContext | None:
        """Initialize mission and return context."""
        try:
            mission.set_status("running")
            mission.log(f"Starting mission against {mission.target}")
            await self.update_db_status(mission)

            # Connect per-mission VPN if configured
            if mission.vpn_config:
                try:
                    from spectra_platform.services.tools.vpn import VPNManager

                    vpn_mgr = VPNManager()
                    result = await vpn_mgr.connect(mission.vpn_config)
                    mission.log(f"[VPN] Connected via '{mission.vpn_config}' (job: {result.get('job_id', 'N/A')})")
                    # Wait for VPN tunnel to establish
                    job_id = result.get("job_id")
                    if job_id:
                        try:
                            from spectra_platform.infrastructure.queue import Job

                            job = Job(job_id)
                            await job.result(timeout=30)
                            mission.log("[VPN] Tunnel established successfully")
                        except (OSError, RuntimeError, TimeoutError):
                            mission.log("[VPN] Warning: tunnel not confirmed after 30s, proceeding anyway")
                            logger.warning("VPN tunnel not confirmed for mission %s after 30s", mission.id)
                except (OSError, RuntimeError, ImportError) as vpn_err:
                    mission.log(f"[VPN] Failed to connect '{mission.vpn_config}': {vpn_err}")
                    logger.error("VPN connect failed for mission %s: %s", mission.id, vpn_err)
            else:
                # Log VPN status
                try:
                    from spectra_platform.services.tools.vpn import VPNManager

                    vpn_mgr = VPNManager()
                    configs = await vpn_mgr.list_configs()
                    if configs:
                        mission.log(f"[VPN] {len(configs)} VPN config(s) available")
                    else:
                        mission.log("[VPN] No VPN connection active - using direct network")
                except (OSError, RuntimeError, ImportError):
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
            sanitized_requirements = ""
            if mission.requirements:
                sanitized_requirements = sanitize_for_prompt(mission.requirements, field_name="requirements")
            if sanitized_requirements:
                effective_mission = f"{mission.directive}\n\nRequirements:\n{sanitized_requirements}"
            user_role, plan_features, tenant_quotas = await _load_capability_context(mission.user_id)

            return AgentContext(
                mission_id=mission.id,
                session_id=mission.id,
                user_id=mission.user_id,
                user_role=user_role,
                plan_features=plan_features,
                tenant_quotas=tenant_quotas,
                target=mission.target,
                mission=effective_mission,
                phase="scope",
                stealth_mode=False,
                max_concurrency=3,
                extra_context="",
                cost_tracker=None,
            )

        except (OSError, RuntimeError, ValueError) as e:
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
        events.emit_sync(EventType.AGENT_STATE, "mission_manager", **data)
