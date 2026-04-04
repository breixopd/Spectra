"""Mission entity - represents an active security assessment mission."""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, ClassVar

from app.core.enums import MissionStatus
from app.core.paths import data_path
from app.core.state_machine import MissionStateMachine
from app.core.websocket import manager as ws_manager
from app.models.attack_surface import (
    AttackSurface,
    DiscoveredService,
    DiscoveredWebApp,
    Vulnerability,
)
from app.services.ai.agents.mission_controller import MissionPlan
from app.services.ai.blackboard import MissionBlackboard, get_blackboard
from app.services.mission.credentials import CredentialStore
from app.services.mission.finding_dedup import (
    RELATED_CVE_GROUPS,
    are_related_cves,
    finding_dedup_key,
    is_duplicate_finding,
    is_fuzzy_duplicate,
    normalize_finding,
)
from app.services.mission.task_tree import PentestTaskTree, TaskStatus
from app.services.mission.types import (
    FindingDict,
    MissionProgress,
    ServiceInfo,
    ToolExecutionRecord,
    VulnInfo,
)
from app.utils.geoip import GeoLocation

logger = logging.getLogger(__name__)


class Mission:
    """
    Represents an active security mission with attack surface tracking.

    Responsibilities:
    - Track mission state (status, phase, findings)
    - Manage attack surface (services, vulnerabilities, vectors)
    - Handle logging and broadcasting
    - Track executed tools for adaptive tool selection

    Does NOT:
    - Execute tasks (see MissionExecutor)
    - Coordinate agents (see MissionManager)
    """

    def __init__(
        self,
        target: str,
        directive: str,
        requirements: str | None = None,
        vpn_config: str | None = None,
        user_id: str | None = None,
        requires_approval: bool = False,
    ):
        self.id = str(uuid.uuid4())
        self.target = target
        self.directive = directive
        self.requirements = requirements
        self.vpn_config = vpn_config
        self.user_id = user_id
        self.requires_approval = requires_approval
        self.status = "created"
        self.start_time = datetime.now()
        self.plan: MissionPlan | None = None
        self.current_task_index = 0
        self.findings: list[dict[str, Any]] = []
        self.logs: list[str] = []
        self._stop_event = asyncio.Event()
        self._paused_event = asyncio.Event()
        self._paused_event.set()  # Initially active (not paused)
        self.geo_info: GeoLocation | None = None

        # State machine for validated transitions
        self.fsm = MissionStateMachine(self.id)

        # Attack Surface tracking
        self.attack_surface = AttackSurface()
        self.exploitation_phase_complete = False
        self.skipped_phases: set[str] = set()

        # Tool execution tracking for adaptive selection
        self.tools_run: list[str] = []
        # Detailed tool execution history with arguments
        self.tool_executions: list[ToolExecutionRecord] = []
        # Report file path when generated
        self.report_path: str | None = None
        # Replan tracking
        self.replan_count: int = 0

        # Mission-scoped logger and logical workspace prefix.
        # Real transient directories are created by the tool-output layer on demand,
        # and persisted data is written through StorageService.
        self._logger = logging.getLogger(f"spectra.mission.{self.id[:8]}")
        self.output_dir = data_path("missions", self.id)

        # Inter-agent shared blackboard
        self.blackboard: MissionBlackboard = get_blackboard(self.id)
        # Formal task tree tracking attack progress
        self.task_tree: PentestTaskTree = PentestTaskTree(self.id)
        # Mission-scoped credential store
        self.credential_store: CredentialStore = CredentialStore()

    # --- State Management ---

    def stop(self) -> None:
        """Signal mission to stop."""
        self._stop_event.set()
        self.status = "stopping"

    def is_stopped(self) -> bool:
        """Check if mission has been stopped."""
        return self._stop_event.is_set()

    def set_status(self, status: str) -> None:
        """Update mission status, validating via FSM when possible."""
        try:
            new_state = MissionStatus(status)
            if self.fsm.can_transition_to(new_state):
                self.fsm.transition_to(new_state)
            else:
                logger.warning(
                    "Invalid FSM transition %s -> %s for mission %s, setting raw status",
                    self.fsm.state.value,
                    status,
                    self.id,
                )
        except ValueError:
            # status string not in MissionStatus enum — just set raw
            logger.debug("Status '%s' not in MissionStatus enum", status)
        self.status = status

    def pause(self) -> None:
        """Pause the mission."""
        self._paused_event.clear()
        self.set_status("paused")
        self.log("Mission paused")

    def resume(self) -> None:
        """Resume the mission."""
        self._paused_event.set()
        self.set_status("running")
        self.log("Mission resumed")

    def replan(self, reason: str, new_tasks: list[Any]) -> bool:
        """Insert new tasks into the mission plan for dynamic replanning.

        Returns True if replanning was applied, False if limit reached.
        """
        from app.core.constants import MAX_REPLANS_PER_MISSION

        if self.replan_count >= MAX_REPLANS_PER_MISSION:
            self.log(f"[REPLAN] Denied: max replans ({MAX_REPLANS_PER_MISSION}) reached")
            return False

        if not self.plan:
            self.log("[REPLAN] Denied: no plan exists")
            return False

        self.replan_count += 1
        # Insert new tasks after the current task index
        insert_idx = self.current_task_index + 1
        for i, task in enumerate(new_tasks):
            self.plan.tasks.insert(insert_idx + i, task)

        self.log(f"[REPLAN] #{self.replan_count}: {reason} — inserted {len(new_tasks)} tasks at index {insert_idx}")
        return True

    async def wait_if_paused(self) -> None:
        """Wait until mission is resumed."""
        await self._paused_event.wait()

    # --- Logging ---

    def log(self, message: str) -> None:
        """Add a log message and broadcast to UI."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] [{self.id[:8]}] {message}"
        self.logs.append(entry)
        self._logger.info("%s", message)
        # Broadcast to UI
        self._broadcast("log", entry)

    def _broadcast(self, msg_type: str, data: Any) -> None:
        """Broadcast a message to the owning user's WebSocket connections."""
        if self.user_id:
            asyncio.create_task(ws_manager.broadcast_to_user_event(self.user_id, msg_type, data))
        else:
            asyncio.create_task(ws_manager.broadcast_event(msg_type, data))

    # --- Attack Surface Management ---

    def add_service(
        self,
        host: str,
        port: int,
        service: str | None = None,
        product: str | None = None,
        version: str | None = None,
    ) -> DiscoveredService:
        """Add a discovered service to the attack surface."""
        svc = DiscoveredService(
            host=host,
            port=port,
            service=service,
            product=product,
            version=version,
        )
        self.attack_surface.add_service(svc)
        self.log(f"Discovered: {host}:{port} ({service or 'unknown'})")
        return svc

    def add_vulnerability(
        self,
        vuln_id: str,
        title: str,
        severity: str,
        cve_id: str | None = None,
    ) -> Vulnerability:
        """Add a discovered vulnerability."""
        vuln = Vulnerability(
            id=vuln_id,
            title=title,
            severity=severity,
            cve_id=cve_id,
        )
        self.attack_surface.add_vulnerability(vuln)
        self.log(f"Vulnerability: {title} ({severity})")
        return vuln

    def add_webapp(
        self,
        url: str,
        technologies: list[str] | None = None,
    ) -> DiscoveredWebApp:
        """Add a discovered web application."""
        app = DiscoveredWebApp(
            url=url,
            technologies=technologies or [],
        )
        self.attack_surface.add_web_app(app)
        self.log(f"Web App: {url} ({', '.join(technologies or [])})")
        return app

    def add_finding(self, finding: FindingDict) -> None:
        """Add a finding to the mission, deduplicating by key fields."""
        finding_data = dict(finding)
        if self._is_duplicate_finding(finding_data):
            return
        if self._is_known_false_positive(finding_data):
            return
        finding_data = self._apply_mitre_tags(finding_data)
        finding_data["count"] = 1
        self.findings.append(finding_data)
        self._broadcast("finding", finding_data)

    def _is_duplicate_finding(self, finding: dict[str, Any]) -> bool:
        """Check for exact or fuzzy duplicates; merge into existing if found."""
        return is_duplicate_finding(self.findings, finding)

    def _is_known_false_positive(self, finding: dict[str, Any]) -> bool:
        """Check if a finding matches a known false positive."""
        try:
            from app.services.ai.memory import get_memory

            memory = get_memory(self.user_id)
            template_id = finding.get("template-id") or finding.get("name", "")
            if template_id and memory.is_false_positive(template_id):
                return True
        except (OSError, RuntimeError, ValueError) as e:
            logger.debug("Non-critical operation failed: %s", e)
        return False

    def _apply_mitre_tags(self, finding: dict[str, Any]) -> dict[str, Any]:
        """Auto-tag a finding with MITRE ATT&CK techniques."""
        try:
            from app.services.ai.mitre_attack import tag_finding_with_attack

            finding = tag_finding_with_attack(finding)
        except (OSError, RuntimeError, ValueError) as e:
            logger.debug("Non-critical operation failed: %s", e)
        return finding

    def _finding_dedup_key(self, finding: dict[str, Any]) -> str:
        """Generate a deduplication key for a finding (normalized for comparison)."""
        return finding_dedup_key(finding)

    @staticmethod
    def _normalize_finding(finding: dict[str, Any]) -> dict[str, Any]:
        """Normalize finding fields for consistent comparison (returns copy)."""
        return normalize_finding(finding)

    _RELATED_CVE_GROUPS: ClassVar[list[set[str]]] = RELATED_CVE_GROUPS

    @classmethod
    def _are_related_cves(cls, cve_a: str | None, cve_b: str | None) -> bool:
        """Check if two CVEs belong to the same related group."""
        return are_related_cves(cve_a, cve_b)

    @staticmethod
    def _is_fuzzy_duplicate(a: dict[str, Any], b: dict[str, Any]) -> bool:
        """Check if two findings are fuzzy duplicates."""
        return is_fuzzy_duplicate(a, b)

    def record_tool_run(
        self,
        tool_id: str,
        args: dict[str, Any] | None = None,
        command: str | None = None,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        """Record that a tool was executed with details."""
        if tool_id not in self.tools_run:
            self.tools_run.append(tool_id)

        # Store detailed execution record
        record: ToolExecutionRecord = {
            "tool": tool_id,
            "args": args or {},
            "command": command,
            "success": success,
            "error": error,
            "timestamp": datetime.now().isoformat(),
        }
        self.tool_executions.append(record)

    def get_known_services(self) -> list[ServiceInfo]:
        """Get discovered services as dicts for agent input."""
        return [
            ServiceInfo(
                host=svc.host,
                port=svc.port,
                protocol=svc.protocol,
                service=svc.service,
                product=svc.product,
                version=svc.version,
            )
            for svc in self.attack_surface.services
        ]

    def get_known_vulns(self) -> list[VulnInfo]:
        """Get discovered vulnerabilities as dicts for agent input."""
        return [
            VulnInfo(
                id=vuln.id,
                name=vuln.title,
                severity=vuln.severity,
                cve_id=vuln.cve_id,
                cvss=vuln.cvss,
            )
            for vuln in self.attack_surface.vulnerabilities
        ]

    def get_progress(self) -> MissionProgress:
        """Estimate mission progress based on task tree state."""
        if not self.task_tree:
            return MissionProgress(percent=0, phase="unknown", eta_minutes=None)

        nodes = self.task_tree._nodes
        total = len(nodes) - 1  # exclude root
        if total <= 0:
            return MissionProgress(
                percent=0,
                phase="initializing",
                completed_tasks=0,
                total_tasks=0,
                active_tasks=[],
            )

        completed = sum(
            1
            for n in nodes.values()
            if n.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED) and n.id != "root"
        )
        active = [n for n in nodes.values() if n.status == TaskStatus.ACTIVE]

        percent = round(completed / total * 100, 1)

        phase = "initializing"
        if active:
            technique = active[0].technique.split("/")[0]
            phase = technique

        return MissionProgress(
            percent=percent,
            phase=phase,
            completed_tasks=completed,
            total_tasks=total,
            active_tasks=[{"id": n.id, "name": n.name} for n in active],
        )

    # --- Serialization ---

    def to_dict(self) -> dict[str, Any]:
        """Serialize mission to dictionary."""
        return {
            "id": self.id,
            "target": self.target,
            "directive": self.directive,
            "requirements": self.requirements,
            "status": self.status,
            "start_time": self.start_time.isoformat(),
            "current_task_index": self.current_task_index,
            "findings_count": len(self.findings),
            "findings": self.findings,
            "logs_count": len(self.logs),
            "logs": self.logs,
            "geo_info": self.geo_info,
            "attack_surface": self.attack_surface.get_summary(),
            "tools_run": self.tools_run or [],  # Always return a list
            "tool_executions": self.tool_executions,
            "report_path": self.report_path,
            "task_tree": self.task_tree.to_dict(),
            "blackboard": self.blackboard.read_all(),
        }

    def save_checkpoint(self) -> dict[str, Any]:
        """Serialize mission state for checkpoint/resume.

        Returns a JSON-serializable dict that captures enough state to
        reconstruct the mission later.
        """
        plan_data = None
        if self.plan:
            try:
                plan_data = self.plan.model_dump()
            except (ValueError, TypeError, KeyError):
                plan_data = None

        return {
            "id": self.id,
            "target": self.target,
            "directive": self.directive,
            "requirements": self.requirements,
            "status": self.status,
            "start_time": self.start_time.isoformat(),
            "current_task_index": self.current_task_index,
            "findings": self.findings,
            "findings_ids": [f.get("id") or f.get("template-id", "") for f in self.findings],
            "tools_run": self.tools_run,
            "tool_executions": self.tool_executions,
            "skipped_phases": list(self.skipped_phases),
            "plan": plan_data,
            "attack_surface": self.attack_surface.model_dump(),
            "replan_count": getattr(self, "replan_count", 0),
            "task_tree": self.task_tree.to_dict(),
        }

    @classmethod
    def from_checkpoint(cls, data: dict[str, Any]) -> "Mission":
        """Reconstruct a Mission from checkpoint data."""
        mission = cls(
            target=data["target"],
            directive=data["directive"],
            requirements=data.get("requirements"),
        )
        mission.id = data["id"]
        mission.status = data.get("status", "created")
        mission.current_task_index = data.get("current_task_index", 0)
        mission.findings = data.get("findings", [])
        mission.tools_run = data.get("tools_run", [])
        mission.tool_executions = data.get("tool_executions", [])
        mission.skipped_phases = set(data.get("skipped_phases", []))
        mission.replan_count = data.get("replan_count", 0)

        # Restore attack surface
        if data.get("attack_surface"):
            try:
                mission.attack_surface = AttackSurface.model_validate(data["attack_surface"])
            except (ValueError, TypeError, KeyError) as e:
                logger.warning("Failed to restore attack surface: %s", e)

        # Restore plan
        if data.get("plan"):
            try:
                from app.services.ai.agents.mission_controller import MissionPlan

                mission.plan = MissionPlan.model_validate(data["plan"])
            except (ValueError, TypeError, KeyError) as e:
                logger.warning("Failed to restore plan: %s", e)

        # Restore task tree
        if data.get("task_tree"):
            try:
                mission.task_tree = PentestTaskTree.from_dict(data["task_tree"])
            except (ValueError, TypeError, KeyError) as e:
                logger.warning("Failed to restore task tree: %s", e)

        return mission
