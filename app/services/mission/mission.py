"""Mission entity - represents an active security assessment mission."""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

from app.core.websocket import manager as ws_manager
from app.models.attack_surface import (
    AttackSurface,
    DiscoveredService,
    DiscoveredWebApp,
    Vulnerability,
)
from app.services.ai.agents.mission_controller import MissionPlan
from app.utils.geoip import GeoLocation

logger = logging.getLogger("spectra.mission")


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

    def __init__(self, target: str, directive: str):
        self.id = str(uuid.uuid4())
        self.target = target
        self.directive = directive
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

        # Attack Surface tracking
        self.attack_surface = AttackSurface()
        self.exploitation_phase_complete = False
        self.skipped_phases: set[str] = set()

        # Tool execution tracking for adaptive selection
        self.tools_run: list[str] = []
        # Detailed tool execution history with arguments
        self.tool_executions: list[dict[str, Any]] = []
        # Report file path when generated
        self.report_path: str | None = None

    # --- State Management ---

    def stop(self) -> None:
        """Signal mission to stop."""
        self._stop_event.set()
        self.status = "stopping"

    def is_stopped(self) -> bool:
        """Check if mission has been stopped."""
        return self._stop_event.is_set()

    def set_status(self, status: str) -> None:
        """Update mission status."""
        self.status = status

    def pause(self) -> None:
        """Pause the mission."""
        self._paused_event.clear()
        self.status = "paused"
        self.log("Mission paused")

    def resume(self) -> None:
        """Resume the mission."""
        self._paused_event.set()
        self.status = "running"
        self.log("Mission resumed")

    async def wait_if_paused(self) -> None:
        """Wait until mission is resumed."""
        await self._paused_event.wait()

    # --- Logging ---

    def log(self, message: str) -> None:
        """Add a log message and broadcast to UI."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        self.logs.append(entry)
        logger.info("Mission %s: %s", self.id, message)
        # Broadcast to UI
        self._broadcast("log", entry)

    def _broadcast(self, msg_type: str, data: Any) -> None:
        """Broadcast a message to WebSocket clients."""
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

    def add_finding(self, finding: dict[str, Any]) -> None:
        """Add a finding to the mission, deduplicating by key fields."""
        # Build dedup key from template-id + host/port, or name + port
        dedup_key = self._finding_dedup_key(finding)

        # Check for duplicates — increment count instead of adding again
        for existing in self.findings:
            if self._finding_dedup_key(existing) == dedup_key:
                existing["count"] = existing.get("count", 1) + 1
                return

        # Check if this is a known false positive
        try:
            from app.services.ai.memory import get_memory

            memory = get_memory()
            template_id = finding.get("template-id") or finding.get("name", "")
            if template_id and memory.is_false_positive(template_id):
                return
        except Exception:
            logger.debug("Ignored exception", exc_info=True)

        # Auto-tag with MITRE ATT&CK techniques
        try:
            from app.services.ai.mitre_attack import tag_finding_with_attack

            finding = tag_finding_with_attack(finding)
        except Exception:
            logger.debug("Ignored exception", exc_info=True)

        finding["count"] = 1
        self.findings.append(finding)
        self._broadcast("finding", finding)

    def _finding_dedup_key(self, finding: dict[str, Any]) -> str:
        """Generate a deduplication key for a finding."""
        template = finding.get("template-id") or finding.get("name") or ""
        host = finding.get("host") or finding.get("ip") or ""
        port = str(finding.get("port") or finding.get("portid") or "")
        matched = finding.get("matched-at") or ""
        return f"{template}|{host}|{port}|{matched}"

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
        self.tool_executions.append(
            {
                "tool": tool_id,
                "args": args or {},
                "command": command,
                "success": success,
                "error": error,
                "timestamp": datetime.now().isoformat(),
            }
        )

    def get_known_services(self) -> list[dict[str, Any]]:
        """Get discovered services as dicts for agent input."""
        return [
            {
                "host": svc.host,
                "port": svc.port,
                "protocol": svc.protocol,
                "service": svc.service,
                "product": svc.product,
                "version": svc.version,
            }
            for svc in self.attack_surface.services
        ]

    def get_known_vulns(self) -> list[dict[str, Any]]:
        """Get discovered vulnerabilities as dicts for agent input."""
        return [
            {
                "id": vuln.id,
                "name": vuln.title,
                "severity": vuln.severity,
                "cve_id": vuln.cve_id,
                "cvss": vuln.cvss,
            }
            for vuln in self.attack_surface.vulnerabilities
        ]

    # --- Serialization ---

    def to_dict(self) -> dict[str, Any]:
        """Serialize mission to dictionary."""
        return {
            "id": self.id,
            "target": self.target,
            "directive": self.directive,
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
        }
