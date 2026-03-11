"""Pentesting Task Tree — formal tree tracking attack progress."""

import logging
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)

class TaskStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class TaskNode:
    id: str
    name: str
    technique: str  # e.g. "recon/port_scan", "exploit/rce", "privesc/suid"
    status: TaskStatus = TaskStatus.PENDING
    parent_id: str | None = None
    children: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)  # finding IDs
    tool_used: str | None = None
    started_at: float | None = None
    completed_at: float | None = None
    details: dict[str, Any] = field(default_factory=dict)


class PentestTaskTree:
    """Formal tree tracking attack progress, inspired by PentestGPT's PTT."""

    def __init__(self, mission_id: str):
        self.mission_id = mission_id
        self.root = TaskNode(id="root", name="Mission Root", technique="mission")
        self._nodes: dict[str, TaskNode] = {"root": self.root}

    def add_task(
        self,
        task_id: str,
        name: str,
        technique: str,
        parent_id: str = "root",
        **kwargs: Any,
    ) -> TaskNode:
        node = TaskNode(
            id=task_id, name=name, technique=technique, parent_id=parent_id, **kwargs
        )
        self._nodes[task_id] = node
        if parent_id in self._nodes:
            self._nodes[parent_id].children.append(task_id)
        return node

    def update_status(self, task_id: str, status: TaskStatus) -> None:
        if task_id in self._nodes:
            self._nodes[task_id].status = status
            if status == TaskStatus.ACTIVE:
                self._nodes[task_id].started_at = time.time()
            elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                self._nodes[task_id].completed_at = time.time()

    def get_node(self, task_id: str) -> TaskNode | None:
        return self._nodes.get(task_id)

    def get_active_tasks(self) -> list[TaskNode]:
        return [n for n in self._nodes.values() if n.status == TaskStatus.ACTIVE]

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API/UI consumption."""
        return {
            "mission_id": self.mission_id,
            "nodes": {k: asdict(v) for k, v in self._nodes.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PentestTaskTree":
        """Deserialize from stored data."""
        tree = cls(data["mission_id"])
        for node_id, node_data in data.get("nodes", {}).items():
            # Convert status string back to enum
            if "status" in node_data and isinstance(node_data["status"], str):
                node_data["status"] = TaskStatus(node_data["status"])
            if node_id == "root":
                tree.root = TaskNode(**node_data)
                tree._nodes["root"] = tree.root
            else:
                tree._nodes[node_id] = TaskNode(**node_data)
        return tree
