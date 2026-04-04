"""Tool validation: name checks, registry resolution, auto-install."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.services.tools.execution import ensure_tool_installed
from app.services.tools.models import RegisteredTool, ToolExecutionResult
from app.services.tools.output import create_error_result, validate_tool_name
from app.services.tools.registry import get_registry

if TYPE_CHECKING:
    from app.services.mission.mission import Mission

logger = logging.getLogger(__name__)

try:
    import jsonschema

    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False
    logger.warning("jsonschema not installed — tool argument validation disabled")


async def validate_and_resolve_tool(
    mission: Mission,
    tool_name: str,
    target: str,
    args: dict[str, Any] | None,
    install_timeout: int,
) -> tuple[RegisteredTool | None, ToolExecutionResult | None]:
    """Validate tool name, resolve from registry, auto-install if needed."""
    if not validate_tool_name(tool_name):
        mission.log(f"Invalid tool name format: {tool_name}")
        return None, create_error_result(tool_name, target, "Invalid tool name")

    registry = get_registry()
    await registry.sync_status_from_cache()
    tool = registry.get_tool(tool_name)

    if not tool:
        mission.log(f"Tool {tool_name} not found in registry")
        return None, create_error_result(tool_name, target, "Tool not available")

    if not tool.is_available:
        mission.log(f"Tool {tool_name} not installed, installing...")
        install_success = await ensure_tool_installed(tool_name, install_timeout)
        if not install_success:
            mission.log(f"Failed to install {tool_name}")
            return None, create_error_result(tool_name, target, "Tool installation failed")
        mission.log(f"Tool {tool_name} installed successfully")
        tool = registry.get_tool(tool_name)
        if not tool:
            return None, create_error_result(tool_name, target, "Tool not found after install")

    if tool.config.execution.args_schema:
        if HAS_JSONSCHEMA:
            try:
                jsonschema.validate(instance=args or {}, schema=tool.config.execution.args_schema)
            except jsonschema.ValidationError as e:
                return None, create_error_result(tool_name, target, f"Invalid arguments: {e}")
        else:
            logger.warning(
                "Skipping argument validation for %s — jsonschema not installed",
                tool_name,
            )

    return tool, None
