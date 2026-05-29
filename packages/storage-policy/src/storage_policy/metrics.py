"""Simple metrics collector for tiered storage operations.

Logs promotion, demotion, and deletion events with timestamps and object
keys.  Designed to be lightweight — no external dependencies beyond the
standard library's logging module.
"""

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TieringEvent:
    """Record of a single tiering operation.

    Attributes:
        timestamp: Unix timestamp when the event occurred.
        key: Object key involved.
        event_type: One of "promote", "demote", "delete".
        source_tier: Tier the object moved from (or None for put/delete).
        target_tier: Tier the object moved to (or None for delete).
    """

    timestamp: float
    key: str
    event_type: str
    source_tier: str | None = None
    target_tier: str | None = None


@dataclass
class MetricsCollector:
    """Collects and logs tiering events in memory.

    Attributes:
        events: In-memory list of recorded events.
        max_events: Maximum number of events to keep in memory.
    """

    events: list[TieringEvent] = field(default_factory=list)
    max_events: int = 10_000

    def record_promotion(self, key: str) -> None:
        """Record an object promotion from COLD to HOT."""
        self._add(TieringEvent(
            timestamp=time.time(),
            key=key,
            event_type="promote",
            source_tier="cold",
            target_tier="hot",
        ))
        logger.info("PROMOTE %s cold -> hot", key)

    def record_demotion(self, key: str) -> None:
        """Record an object demotion from HOT to COLD."""
        self._add(TieringEvent(
            timestamp=time.time(),
            key=key,
            event_type="demote",
            source_tier="hot",
            target_tier="cold",
        ))
        logger.info("DEMOTE %s hot -> cold", key)

    def record_deletion(self, key: str) -> None:
        """Record an object deletion (e.g., GC)."""
        self._add(TieringEvent(
            timestamp=time.time(),
            key=key,
            event_type="delete",
        ))
        logger.info("DELETE %s", key)

    def _add(self, event: TieringEvent) -> None:
        self.events.append(event)
        if len(self.events) > self.max_events:
            self.events = self.events[-self.max_events:]

    def recent_events(self, n: int = 50) -> list[TieringEvent]:
        """Return the *n* most recent events."""
        return self.events[-n:]
