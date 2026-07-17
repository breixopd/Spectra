"""Small structural contracts shared by tool-execution entry points."""

from __future__ import annotations

from typing import Protocol


class ToolExecutionMission(Protocol):
    """The mission context required to run a tool or generated script.

    This deliberately exposes only the state consumed by the execution and
    safety layers.  It permits a durable Mission and the standalone POC
    adapter to share one safe execution path without pretending that the
    adapter is a full mission aggregate.
    """

    @property
    def id(self) -> str: ...

    @property
    def target(self) -> str: ...

    @property
    def user_id(self) -> str | None: ...

    @property
    def directive(self) -> str: ...

    def log(self, message: str) -> None:
        """Record a user-visible execution event."""
