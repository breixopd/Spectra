"""Tool validation: name checks, registry resolution, golden-image readiness."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.services.tools.output import create_error_result, validate_tool_name
from app.services.tools.registry import get_registry
from spectra_tools_core.models import RegisteredTool, ToolExecutionResult

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.services.mission.mission import Mission

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
) -> tuple[RegisteredTool | None, ToolExecutionResult | None]:
    """Validate tool name and resolve from registry.

    Runtime execution workers must use prebuilt, verified golden images. Missing
    tools are deployment/build failures, not mission-time installation work.
    """
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
        mission.log(f"Tool {tool_name} readiness is pending; worker will verify the installed binary before execution")

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
