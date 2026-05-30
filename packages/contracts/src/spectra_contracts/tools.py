"""Tool port interfaces."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ToolRuntimePort(Protocol):
    """Port interface for checking tool runtime availability."""

    def is_tool_installed(self, tool: Any) -> bool: ...
