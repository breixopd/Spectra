"""Sandbox data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class SandboxInfo:
    """Immutable snapshot of a sandbox's state."""

    container_id: str
    container_name: str
    mission_id: str
    queue_name: str
    status: str
    image: str
    resource_tier: str = "medium"
    network_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @staticmethod
    def make_queue_name(mission_id: str) -> str:
        """Derive the deterministic queue name for a mission."""
        # Use first 8 chars of UUID — unique enough, stays within queue regex
        prefix = mission_id.replace("-", "")[:8].lower()
        return f"mission_{prefix}"
