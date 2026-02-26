import json
import logging
from pathlib import Path

import aiofiles

from app.services.tools.models import (
    RegisteredTool,
    ToolStatus,
)
from app.services.tools.registry.validator import PluginValidator

logger = logging.getLogger("spectra.tools.registry.loader")


class PluginLoader:
    """Handles loading of plugin files from disk."""

    def __init__(self, plugins_dir: Path, validator: PluginValidator):
        self.plugins_dir = plugins_dir
        self.validator = validator

    async def load_plugins(
        self, existing_tools: dict[str, RegisteredTool]
    ) -> dict[str, RegisteredTool]:
        """Scan the plugins directory and load all valid plugins.

        Args:
            existing_tools: Current dictionary of loaded tools (to preserve status).

        Returns:
            Updated dictionary of tool_id -> RegisteredTool.
        """
        if not self.plugins_dir.exists():
            logger.warning("Plugins directory does not exist: %s", self.plugins_dir)
            return existing_tools

        loaded_ids = set()
        tools = existing_tools.copy()

        for json_file in self.plugins_dir.glob("*.json"):
            try:
                tool_id = await self._load_plugin_file(json_file, tools)

                # Enforce consistency between filename and ID
                if json_file.stem != tool_id:
                    logger.warning(
                        "Plugin ID '%s' does not match filename '%s'. This may cause issues.",
                        tool_id,
                        json_file.name,
                    )

                loaded_ids.add(tool_id)
            except Exception as e:
                logger.error("Failed to load plugin %s: %s", json_file.name, e)

        # Remove tools that are no longer on disk
        current_tool_ids = list(tools.keys())
        for tool_id in current_tool_ids:
            if tool_id not in loaded_ids:
                logger.info("Removing tool '%s' as it is no longer on disk.", tool_id)
                del tools[tool_id]

        return tools

    async def _load_plugin_file(
        self, path: Path, tools: dict[str, RegisteredTool]
    ) -> str:
        """Load a single plugin file."""
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            content = await f.read()
            data = json.loads(content)

        # Validate schema (uses the validator passed in init)
        config = self.validator.validate_plugin(data)

        # Determine initial status based on system availability
        status = ToolStatus.PENDING
        if config.id in tools:
            # Preserve status if reloading
            status = tools[config.id].status
        else:
            # Check if tool is already installed in the tools container
            status = await self._check_tool_availability(config)

        tools[config.id] = RegisteredTool(
            config=config,
            status=status,
        )
        logger.debug(
            "Registered plugin: %s (%s) [Status: %s]", config.id, config.name, status
        )
        return config.id

    async def _check_tool_availability(self, config) -> ToolStatus:
        """Check if a tool is available.

        For the app container, we assume tools are PENDING until explicitly installed.
        The worker in the tools container will check availability when running jobs.
        This avoids needing docker CLI in the app container.
        """
        import os

        # If we're in the tools container, check locally
        is_tools_container = os.environ.get("IS_TOOLS_CONTAINER", "").lower() == "true"

        if is_tools_container:
            import shutil

            # Get main executable from command string
            cmd_parts = config.execution.command.split()
            if cmd_parts:
                executable = cmd_parts[0]
                if shutil.which(executable):
                    logger.debug("Tool %s is available locally", config.id)
                    return ToolStatus.READY

        # For app container or if tool not found, default to PENDING
        # Tools will be installed on-demand via the worker
        return ToolStatus.PENDING
