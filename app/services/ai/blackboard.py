"""Mission-scoped shared blackboard for inter-agent communication."""

from __future__ import annotations

import json
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

    def _estimate_size(self, value: Any) -> int:
        """Estimate the size of a value in bytes."""
        try:
            return len(json.dumps(value, default=str))
        except (TypeError, ValueError):
            return sys.getsizeof(value)

    def write(self, agent_role: str, key: str, value: Any) -> None:
        """Write a fact/insight to the blackboard."""
        if self._estimate_size(value) > MAX_VALUE_SIZE:
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

    async def persist_to_db(self, mission_id: str | None = None):
        """Persist current blackboard state to PostgreSQL for cross-mission learning."""
        from sqlalchemy import text

        from app.core.database import async_session_maker

        mid = mission_id or self.mission_id
        key = f"blackboard:{mid}"
        data = json.dumps({
            "data": {k: v for k, v in self._data.items()},
            "history": self._history,
        })
        async with async_session_maker() as session:
            await session.execute(
                text("""
                    INSERT INTO system_cache (key, value, expires_at)
                    VALUES (:key, :value, now() + interval '30 days')
                    ON CONFLICT (key) DO UPDATE SET value = :value, expires_at = now() + interval '30 days'
                """),
                {"key": key, "value": data}
            )
            await session.commit()

    async def restore_from_db(self, mission_id: str | None = None) -> bool:
        """Restore blackboard state from a previous mission."""
        from sqlalchemy import text

        from app.core.database import async_session_maker

        mid = mission_id or self.mission_id
        async with async_session_maker() as session:
            result = await session.execute(
                text("SELECT value FROM system_cache WHERE key = :key AND (expires_at IS NULL OR expires_at > now())"),
                {"key": f"blackboard:{mid}"}
            )
            row = result.fetchone()
            if row:
                data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                self._data.update(data.get("data", {}))
                self._history.extend(data.get("history", []))
                return True
        return False

    async def get_cross_mission_findings(self, target_address: str) -> list[dict]:
        """Retrieve findings from previous missions against the same target."""
        from sqlalchemy import text

        from app.core.database import async_session_maker

        async with async_session_maker() as session:
            result = await session.execute(
                text("""
                    SELECT key, value FROM system_cache
                    WHERE key LIKE 'blackboard:%'
                    AND value::text LIKE :target_pattern
                    AND (expires_at IS NULL OR expires_at > now())
                    ORDER BY key DESC LIMIT 5
                """),
                {"target_pattern": f"%{target_address}%"}
            )
            findings: list[dict] = []
            for row in result.fetchall():
                data = json.loads(row[1]) if isinstance(row[1], str) else row[1]
                entries = data.get("data", {})
                for k, v in entries.items():
                    if "finding" in k.lower() or "vuln" in k.lower():
                        findings.append(v)
            return findings


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
