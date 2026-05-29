"""TaskDecomposer — breaks plan tasks into single-tool-call micro-tasks.

Converts high-level mission plan tasks from the MissionController into
fine-grained micro-tasks, each representing ONE tool invocation. This
enables subtask-level error correction (MAKER/MDAP pattern).

Each micro-task has:
- A single tool name + arguments
- A technique category (for framework enforcement)
- Dependencies on other micro-tasks
- Expected output schema for verification
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from spectra_platform.services.mission.framework_loader import FrameworkSpec, get_framework

logger = logging.getLogger(__name__)


@dataclass
class MicroTask:
    """A single, bounded unit of work — one tool call."""

    id: str
    tool_name: str
    tool_args: dict[str, Any]
    technique_category: str
    phase: str
    depends_on: list[str] = field(default_factory=list)
    priority: int = 5  # 1=highest, 10=lowest
    max_retries: int = 2
    expected_output_type: str = "structured"  # structured, text, binary
    metadata: dict[str, Any] = field(default_factory=dict)


class TaskDecomposer:
    """Decomposes high-level plan tasks into executable micro-tasks.

    A plan task like "Scan target for open ports and services" becomes:
    - MicroTask: nmap TCP scan on port 1-1000
    - MicroTask: nmap UDP scan on top 100 ports
    - MicroTask: nmap service version detection

    Each micro-task is independently checkable, retryable, and verifiable.
    """

    def __init__(self, framework_id: str | None = None):
        self.framework: FrameworkSpec = get_framework(framework_id)

    def decompose(self, plan_task: dict[str, Any], phase: str) -> list[MicroTask]:
        """Decompose a single plan task into micro-tasks.

        Args:
            plan_task: Dict with keys: 'action', 'tool' (optional), 'agent_type', 'priority'
            phase: Current assessment phase

        Returns:
            List of micro-tasks, potentially single-item if already minimal
        """
        task_type = plan_task.get("agent_type") or plan_task.get("action", "")
        tool_name = plan_task.get("tool") or plan_task.get("tool_name", "")
        priority = plan_task.get("priority", 5)

        # If the task already specifies a single tool → single micro-task
        if tool_name:
            return [
                MicroTask(
                    id=f"{task_type}_{tool_name}_{hash(str(plan_task)) % 10000}",
                    tool_name=tool_name,
                    tool_args=plan_task.get("args") or plan_task.get("tool_args") or {},
                    technique_category=self._infer_technique(task_type, tool_name),
                    phase=phase,
                    priority=priority,
                )
            ]

        # If multi-tool, decompose by common patterns
        if "scan" in task_type.lower() or "recon" in task_type.lower():
            return self._decompose_scan_task(plan_task, phase, priority)

        if "exploit" in task_type.lower():
            return self._decompose_exploit_task(plan_task, phase, priority)

        # Default: single micro-task with generic tool
        return [
            MicroTask(
                id=f"{task_type}_default_{hash(str(plan_task)) % 10000}",
                tool_name=tool_name or "generic",
                tool_args=plan_task.get("args") or {},
                technique_category=self._infer_technique(task_type, ""),
                phase=phase,
                priority=priority,
            )
        ]

    # ── Decomposition patterns ────────────────────────────────────────

    def _decompose_scan_task(self, task: dict, phase: str, priority: int) -> list[MicroTask]:
        """Break a scan task into parallel port scan + service detection."""
        base_args = task.get("args") or {}
        target = base_args.get("target", "")
        task_id = f"scan_{hash(str(task)) % 10000}"

        return [
            MicroTask(
                id=f"{task_id}_tcp",
                tool_name="nmap",
                tool_args={"target": target, "scan_type": "tcp", "ports": "1-1000"},
                technique_category="port_scanning",
                phase=phase,
                priority=priority,
            ),
            MicroTask(
                id=f"{task_id}_sv",
                tool_name="nmap",
                tool_args={"target": target, "scan_type": "service_version"},
                technique_category="service_enumeration",
                phase=phase,
                depends_on=[f"{task_id}_tcp"],
                priority=priority + 1,
            ),
        ]

    def _decompose_exploit_task(self, task: dict, phase: str, priority: int) -> list[MicroTask]:
        """Break exploit task into craft + execute + verify steps."""
        tool = task.get("tool", "")
        target = (task.get("args") or {}).get("target", "")
        task_id = f"exploit_{hash(str(task)) % 10000}"

        return [
            MicroTask(
                id=f"{task_id}_craft",
                tool_name=tool or "exploit_craft",
                tool_args={"target": target, "action": "select_exploit"},
                technique_category="exploitation",
                phase=phase,
                priority=priority,
            ),
            MicroTask(
                id=f"{task_id}_exec",
                tool_name=tool or "exploit_exec",
                tool_args={"target": target, "action": "execute"},
                technique_category="exploitation",
                phase=phase,
                depends_on=[f"{task_id}_craft"],
                priority=priority + 1,
            ),
            MicroTask(
                id=f"{task_id}_verify",
                tool_name="exploit_verify",
                tool_args={"target": target, "action": "verify_success"},
                technique_category="exploitation",
                phase=phase,
                depends_on=[f"{task_id}_exec"],
                priority=priority + 2,
            ),
        ]

    # ── Helpers ────────────────────────────────────────────────────────

    def _infer_technique(self, task_type: str, tool_name: str) -> str:
        """Infer the technique category from task type and tool name."""
        task_lower = (task_type + tool_name).lower()

        if any(k in task_lower for k in ("scan", "nmap", "naabu", "httpx")):
            return "port_scanning"
        if any(k in task_lower for k in ("nuclei", "vuln", "cve")):
            return "vulnerability_scanning"
        if any(k in task_lower for k in ("exploit", "msf", "metasploit", "poc")):
            return "exploitation"
        if any(k in task_lower for k in ("post", "privesc", "peas", "escal")):
            return "privilege_escalation"
        if any(k in task_lower for k in ("cred", "auth", "password", "hash", "hydra")):
            return "credential_testing"
        if any(k in task_lower for k in ("web", "http", "ffuf", "gobuster", "sql")):
            return "web_scanning"
        if any(k in task_lower for k in ("dns", "subdomain", "amass", "subfinder")):
            return "dns_enumeration"

        return "port_scanning"  # default
