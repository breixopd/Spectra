"""Mission-scoped shared blackboard for inter-agent communication."""

import logging
import sys
import time
from typing import Any

logger = logging.getLogger(__name__)

MAX_ENTRIES = 1000
MAX_VALUE_SIZE = 100_000  # 100 KB per entry
MAX_HISTORY = 5000


class MissionBlackboard:
    """Shared memory for inter-agent communication within a mission."""

    def __init__(self, mission_id: str):
        self.mission_id = mission_id
        self._data: dict[str, dict[str, Any]] = {}
        self._history: list[dict[str, Any]] = []

    def write(self, agent_role: str, key: str, value: Any) -> None:
        """Write a fact/insight to the blackboard."""
        if sys.getsizeof(value) > MAX_VALUE_SIZE:
            logger.warning("Blackboard value for '%s' exceeds %d bytes, rejected", key, MAX_VALUE_SIZE)
            return

        if key not in self._data and len(self._data) >= MAX_ENTRIES:
            oldest_key = next(iter(self._data))
            del self._data[oldest_key]
            logger.warning("Blackboard evicted oldest entry '%s' (max %d)", oldest_key, MAX_ENTRIES)

        self._data[key] = {
            "value": value,
            "author": agent_role,
            "timestamp": time.time(),
        }
        self._history.append({"action": "write", "key": key, "agent": agent_role})
        if len(self._history) > MAX_HISTORY:
            self._history = self._history[-MAX_HISTORY:]

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
