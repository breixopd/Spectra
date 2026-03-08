"""Mission-scoped shared blackboard for inter-agent communication."""

import time
from typing import Any


class MissionBlackboard:
    """Shared memory for inter-agent communication within a mission."""

    def __init__(self, mission_id: str):
        self.mission_id = mission_id
        self._data: dict[str, dict[str, Any]] = {}
        self._history: list[dict[str, Any]] = []

    def write(self, agent_role: str, key: str, value: Any) -> None:
        """Write a fact/insight to the blackboard."""
        self._data[key] = {
            "value": value,
            "author": agent_role,
            "timestamp": time.time(),
        }
        self._history.append({"action": "write", "key": key, "agent": agent_role})

    def read(self, key: str) -> Any | None:
        """Read a value from the blackboard."""
        entry = self._data.get(key)
        return entry["value"] if entry else None

    def read_all(self) -> dict[str, Any]:
        """Get all current blackboard data."""
        return {k: v["value"] for k, v in self._data.items()}

    def get_context_for_agent(self, agent_role: str) -> str:
        """Get formatted context string for injecting into agent prompts."""
        if not self._data:
            return ""
        lines = ["[Shared Intelligence from other agents]"]
        for key, entry in self._data.items():
            lines.append(f"- {key}: {entry['value']} (from {entry['author']})")
        return "\n".join(lines)

    def get_history(self) -> list[dict[str, Any]]:
        """Return the history of writes."""
        return list(self._history)


# Module-level registry of blackboards per mission
_blackboards: dict[str, MissionBlackboard] = {}


def get_blackboard(mission_id: str) -> MissionBlackboard:
    """Get or create a blackboard for the given mission."""
    if mission_id not in _blackboards:
        _blackboards[mission_id] = MissionBlackboard(mission_id)
    return _blackboards[mission_id]


def remove_blackboard(mission_id: str) -> None:
    """Remove the blackboard for a completed/cancelled mission."""
    _blackboards.pop(mission_id, None)
