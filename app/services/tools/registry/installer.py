import logging
import re
from typing import TYPE_CHECKING, Any

from app.services.tools.models import (
    InstallationMethod,
    ToolConfig,
    ToolStatus,
)
from app.services.tools.registry.constants import MAX_OUTPUT_SIZE, MAX_REGEX_LENGTH
from app.services.tools.registry.exceptions import PluginInstallationError
from app.services.tools.registry.executor import run_command_safe

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from app.services.tools.models import RegisteredTool

logger = logging.getLogger("spectra.tools.registry.installer")


class PluginInstaller:
    """Handles installation and uninstallation of tools."""

    async def install_tool(
        self,
        tool: "RegisteredTool",
        progress_callback: "Callable[[dict[str, Any]], Awaitable[None]] | None" = None,
    ) -> bool:
        """Install a tool by executing its installation commands."""
        tool_id = tool.config.id
        config = tool.config

        # Guard against concurrent installs
        if tool.status == ToolStatus.INSTALLING:
            logger.warning("Tool %s is already being installed", tool_id)
            return False

        # Update status
        tool.status = ToolStatus.INSTALLING
        if progress_callback:
            await progress_callback({"status": "installing", "tool_id": tool_id})

        try:
            # Check if already installed via verification command
            if config.installation.verification_command:
                is_verified = await self._verify_installation(config)
                if is_verified:
                    logger.info("Tool %s is already installed (verified)", tool_id)
                    tool.status = ToolStatus.READY
                    if progress_callback:
                        await progress_callback({"status": "ready", "tool_id": tool_id})
                    return True

            # Handle different installation methods
            if config.installation.method == InstallationMethod.NONE:
                # Already installed
                tool.status = ToolStatus.READY
                if progress_callback:
                    await progress_callback({"status": "ready", "tool_id": tool_id})
                return True

            # Execute installation commands
            for i, cmd in enumerate(config.installation.commands):
                if not cmd or not cmd.strip():
                    continue

                logger.info(
                    "Installing %s: Running command %d/%d",
                    tool_id,
                    i + 1,
                    len(config.installation.commands),
                )

                if progress_callback:
                    await progress_callback(
                        {
                            "status": "running",
                            "tool_id": tool_id,
                            "command_index": i,
                            "command": cmd,
                        }
                    )

                returncode, stdout, stderr = await run_command_safe(cmd)

                if returncode != 0:
                    raise PluginInstallationError(
                        f"Command failed (exit {returncode}): {stderr}"
                    )

            # Verify installation
            if config.installation.verification_command:
                verified = await self._verify_installation(config)
                if not verified:
                    raise PluginInstallationError("Verification command failed")

            # Success
            tool.status = ToolStatus.READY
            tool.installed_version = config.version

            if progress_callback:
                await progress_callback({"status": "ready", "tool_id": tool_id})

            logger.info("Successfully installed %s", tool_id)
            return True

        except Exception as e:
            tool.status = ToolStatus.FAILED
            tool.error_message = str(e)

            if progress_callback:
                await progress_callback(
                    {
                        "status": "failed",
                        "tool_id": tool_id,
                        "error": str(e),
                    }
                )

            logger.error("Failed to install %s: %s", tool_id, e)
            raise

    async def uninstall_tool(
        self,
        tool: "RegisteredTool",
        plugins_dir: Any,  # Path
        progress_callback: "Callable[[dict[str, Any]], Awaitable[None]] | None" = None,
    ) -> bool:
        """Uninstall a tool."""
        tool_id = tool.config.id
        config = tool.config

        # execute uninstallation commands
        if config.installation.uninstall_commands:
            logger.info("Uninstalling %s", tool_id)
            if progress_callback:
                await progress_callback({"status": "uninstalling", "tool_id": tool_id})

            try:
                for i, cmd in enumerate(config.installation.uninstall_commands):
                    if not cmd or not cmd.strip():
                        continue

                    logger.info(
                        "Uninstalling %s: Running command %d/%d",
                        tool_id,
                        i + 1,
                        len(config.installation.uninstall_commands),
                    )

                    if progress_callback:
                        await progress_callback(
                            {
                                "status": "running",
                                "tool_id": tool_id,
                                "command_index": i,
                                "command": cmd,
                            }
                        )

                    returncode, stdout, stderr = await run_command_safe(cmd)

                    if returncode != 0:
                        raise PluginInstallationError(
                            f"Uninstall command failed (exit {returncode}): {stderr}"
                        )
            except Exception as e:
                logger.error("Failed to uninstall %s: %s", tool_id, e)
                # We still try to remove the plugin file even if commands fail
                pass

        return True

    async def _verify_installation(self, config: ToolConfig) -> bool:
        """Run the verification command and check output."""
        cmd = config.installation.verification_command
        if not cmd:
            return True

        returncode, stdout, stderr = await run_command_safe(cmd)

        # Check regex if provided
        if config.installation.verification_regex:
            pattern_str = config.installation.verification_regex

            # Guard against ReDoS: limit pattern length
            if len(pattern_str) > MAX_REGEX_LENGTH:
                logger.warning(
                    "Verification regex for %s exceeds max length (%d > %d)",
                    config.id,
                    len(pattern_str),
                    MAX_REGEX_LENGTH,
                )
                return False

            try:
                # Pre-compile to catch invalid regex early
                pattern = re.compile(pattern_str)
            except re.error as e:
                logger.warning("Invalid verification regex for %s: %s", config.id, e)
                return False

            # Limit input size for regex matching to prevent catastrophic backtracking
            combined_output = (stdout + stderr)[:MAX_OUTPUT_SIZE]
            if pattern.search(combined_output):
                # If regex matches, we consider it a success even if exit code is non-zero
                return True
            else:
                logger.debug(
                    "Verification regex for %s did not match output", config.id
                )

        if returncode != 0:
            logger.error(
                "Verification command for %s failed with exit code %d. Stdout: %s, Stderr: %s",
                config.id,
                returncode,
                stdout,
                stderr,
            )
            return False

        return True
