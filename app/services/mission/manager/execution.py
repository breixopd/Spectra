"""Mission execution logic."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, cast

from app.core.constants import (
    MAX_HOSTS_DEFAULT,
)
from app.core.events import events
from app.services.ai.agents.base import AgentContext
from app.services.ai.agents.mission_controller import (
    MissionController,
    MissionInput,
    MissionPlan,
)
from app.services.ai.agents.scope import ScopeAgent, ScopeInput
from app.services.ai.consensus import QualityGate, VotingSystem
from app.services.ai.cost_tracker import CostTracker
from app.services.ai.llm import get_global_llm_client
from app.services.mission.executor import MissionExecutor
from app.services.mission.manager.checkpoint import index_to_rag, record_mission_lessons
from app.services.mission.manager.helpers import (
    execute_mission_tasks,
    generate_html_report,
    run_debrief,
)
from app.services.mission.manager.lifecycle import MissionLifecycleManager
from app.services.mission.manager.steering import MissionSteeringManager
from app.services.mission.mission import Mission
from app.services.shell.session_manager import shell_manager

logger = logging.getLogger(__name__)


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
        # Initialize demo recorder if requested
        recorder = None
        if getattr(mission, "record_demo", False):
            try:
                from app.services.mission.demo_recorder import DemoRecorder

                recorder = DemoRecorder(mission.id, mission.target)
                recorder.start()
                mission.log("[RECORD] Demo recording started")
            except Exception as e:
                logger.debug("Demo recorder init failed: %s", e)

        context = await self.lifecycle.initialize_mission(mission)
        if context is None:
            return

        # Initialize cost tracker for the mission
        cost_tracker = CostTracker(str(mission.id))
        cost_tracker.register()
        context.cost_tracker = cost_tracker

        # Attach cost tracker to agents
        for agent in (self.scope_agent, self.mission_controller):
            if agent:
                agent._cost_tracker = cost_tracker
        if self.executor:
            for agent in self.executor.agents.values():
                agent._cost_tracker = cost_tracker

        # Track mission start time for timeout
        mission_start_time = time.time()
        mission._start_wall_time = mission_start_time  # type: ignore[attr-defined]

        # Send start notification
        try:
            from app.services.notifications import notify_mission_started

            await notify_mission_started(mission.target, mission.directive)
        except Exception as e:
            logger.warning("Failed to send mission start notification: %s", e)

        # Create per-mission sandbox container
        sandbox_info = None
        try:
            from app.services.tools.sandbox import get_sandbox_pool

            pool = get_sandbox_pool()
            if pool and pool.available:
                vpn_path = None
                if getattr(mission, "vpn_config", None):
                    from pathlib import Path

                    from app.core.config import get_settings
                    vpn_dir = Path(get_settings().VPN_CONFIG_DIR)
                    vpn_path = str(vpn_dir / mission.vpn_config)
                    if not (vpn_dir / mission.vpn_config).exists():
                        vpn_path = None
                        mission.log(f"[WARN] VPN config '{mission.vpn_config}' not found, skipping VPN")

                sandbox_info = await pool.create(mission.id, vpn_config_path=vpn_path)
                mission.log(f"[SANDBOX] Created sandbox: {sandbox_info.container_name} (queue={sandbox_info.queue_name})")
            else:
                mission.log("[WARN] Sandbox pool unavailable — tools will use default queue")
        except Exception as e:
            logger.error("Failed to create sandbox for mission %s: %s", mission.id, e)
            mission.log(f"[ERROR] Sandbox creation failed: {e}")

        try:
            # 1. Define Scope
            await self._run_scope_phase(mission, context)

            # 2. Create and validate plan
            await self._run_planning_phase(mission, context)

            if mission.plan is None:
                raise RuntimeError("No plan created")

            # 3. Execute tasks (with demo recording)
            if recorder:
                mission._demo_recorder = recorder
            await self._execute_mission_tasks(mission, context)

            # 4. Post-mission learning
            record_mission_lessons(mission)
            await index_to_rag(mission)

            # 5. Run AI debrief
            await run_debrief(mission, context, self.mission_controller)

            # 6. Generate HTML report
            await generate_html_report(mission)

            # 7. Complete
            mission.set_status("completed")
            mission.log("Mission completed successfully")
            self._broadcast_state("mission_controller", "idle", plan="Mission Complete")

            # Log cost summary
            summary = cost_tracker.get_summary()
            mission.log(
                f"[COST] Total: ${summary['total_cost_usd']:.4f} | "
                f"Tokens: {summary['total_tokens']} | "
                f"Calls: {summary['total_calls']} | "
                f"Duration: {summary['duration_seconds']}s"
            )
            logger.info("Mission %s cost summary: %s", mission.id, summary)

            # Save demo recording
            if recorder:
                recorder.stop()
                path = await recorder.save()
                if path:
                    mission.log(f"[RECORD] Demo saved: {path}")

            # Send completion notification
            try:
                from app.services.notifications import notify_mission_completed

                critical = sum(
                    1
                    for f in mission.findings
                    if str(f.get("severity", "")).lower() == "critical"
                )
                await notify_mission_completed(
                    mission.target, len(mission.findings), critical
                )
            except Exception as e:
                logger.warning("Failed to send mission completion notification: %s", e)

            # Send completion email to mission owner
            try:
                if mission.user_id:
                    from sqlalchemy import select

                    from app.core.config import get_settings
                    from app.core.database import async_session_maker
                    from app.models.user import User
                    from app.services.email import EmailService

                    async with async_session_maker() as db_session:
                        result = await db_session.execute(
                            select(User).where(User.id == mission.user_id)
                        )
                        owner = result.scalar_one_or_none()
                    if owner:
                        _settings = get_settings()
                        base_url = _settings.PLATFORM_BASE_URL or "http://localhost:5000"
                        email_svc = EmailService()
                        await email_svc.send_template(
                            to=owner.email,
                            template_name="mission_complete",
                            subject=f"Spectra \u2014 Mission Complete: {mission.target}",
                            username=owner.username,
                            target=mission.target,
                            status="Completed",
                            finding_count=str(len(mission.findings)),
                            report_url=f"{base_url}/reports/{mission.id}",
                        )
            except Exception as e:
                logger.warning("Failed to send mission completion email: %s", e)

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
            # Destroy per-mission sandbox container
            try:
                from app.services.tools.sandbox import get_sandbox_pool

                pool = get_sandbox_pool()
                if pool and pool.available:
                    await pool.destroy(mission.id)
                    mission.log("[SANDBOX] Sandbox destroyed")
            except Exception as e:
                logger.warning("Sandbox destroy failed for mission %s: %s", mission.id, e)

            # Disconnect per-mission VPN if one was connected
            if getattr(mission, "vpn_config", None):
                try:
                    from app.services.tools.vpn import VPNManager
                    vpn_mgr = VPNManager()
                    await vpn_mgr.disconnect(mission.vpn_config)
                    mission.log(f"[VPN] Disconnected '{mission.vpn_config}'")
                except Exception as vpn_err:
                    logger.error("VPN disconnect failed for mission %s: %s", mission.id, vpn_err)

            # Notify shell manager to update TTLs for active shells from other missions
            try:
                shell_manager.notify_mission_complete(str(mission.id))
            except Exception as e:
                logger.error(
                    f"Failed to notify shell manager of mission completion: {e}"
                )

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
                max_hosts=MAX_HOSTS_DEFAULT,
            ),
        )

        self._broadcast_state("scope_agent", "idle")

        if (
            not scope_result.success
            and scope_result.action
            and not scope_result.action.targets
            and mission.target
        ):
            from app.services.ai.agents.scope import TargetSpec
            scope_result.action.targets = [TargetSpec(
                value=mission.target,
                target_type="hostname",
                notes="Direct target from mission input",
            )]
            scope_result.success = True
            scope_result.error = None

        if not scope_result.success:
            raise RuntimeError(f"Scoping failed: {scope_result.error}")

        target_count = len(scope_result.action.targets)  # type: ignore
        mission.log(f"Scope defined: {target_count} targets")

    async def _run_planning_phase(
        self, mission: Mission, context: AgentContext
    ) -> None:
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

        # Validate plan at PLAN quality gate
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

        mission.log(
            f"[APPROVED] Plan validated (Confidence: {vote_result.average_confidence:.2f})"
        )
        mission.plan = plan_action

        task_count = len(mission.plan.tasks)
        mission.log(f"Plan created: {task_count} tasks")
        self._broadcast_state(
            "mission_controller", "running", plan=f"{task_count} tasks planned"
        )

    async def _execute_mission_tasks(
        self, mission: Mission, context: AgentContext
    ) -> None:
        """Execute all mission tasks with dynamic plan adaptation."""
        await execute_mission_tasks(
            mission, context,
            self.executor, self.mission_controller, self.consensus,
            self.steering, self.lifecycle,
        )

    def _broadcast_state(self, agent_id: str, status: str, **kwargs: Any) -> None:
        """Broadcast agent state."""
        self._broadcast(
            "agent_state", {"agent_id": agent_id, "status": status, **kwargs}
        )

    def _broadcast(self, msg_type: str, data: Any) -> None:
        """Broadcast to WebSocket clients via EventBus."""
        events.emit_sync(msg_type, "mission_manager", **data)
