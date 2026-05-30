"""Tool runtime helpers — checking tool installation status on host."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

TOOLS_PATH_PREFIX = "/opt/spectra_tools"


def _get_executable(tool: object) -> str:
    """Get the executable name from a tool's command."""
    cmd_parts = getattr(getattr(tool, "config", None), "execution", None)
    if cmd_parts is None:
        return getattr(getattr(tool, "config", tool), "id", str(tool))
    command = getattr(cmd_parts, "command", "")
    parts = command.split()
    return parts[0] if parts else getattr(getattr(tool, "config", tool), "id", str(tool))


def _is_tool_installed(tool: object) -> bool:
    """Check if a tool is installed on the host filesystem."""
    executable = _get_executable(tool)

    if shutil.which(executable):
        return True

    persistence_path = Path(TOOLS_PATH_PREFIX) / executable
    return bool(persistence_path.exists() and os.access(persistence_path, os.X_OK))
