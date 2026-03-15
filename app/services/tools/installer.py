import asyncio
import logging
import shutil
from pathlib import Path

from app.services.tools.registry import get_registry

logger = logging.getLogger(__name__)


class ToolInstaller:
    """Service to handle tool installation and verification."""

    def __init__(self, check_persistence: bool = True) -> None:
        self.check_persistence = check_persistence
        self.tools_path = Path("/opt/spectra_tools")

    async def install(self, tool_id: str, progress_callback=None) -> dict:
        """
        Install a tool by ID.

        Args:
            tool_id: The ID of the tool to install.

        Returns:
            Dictionary with installation result.
        """
        logger.info("Installing tool '%s'", tool_id)
        registry = get_registry()

        # Reload plugins if unknown
        if tool_id not in registry._tools:
            logger.info("Tool '%s' not found, reloading plugins...", tool_id)
            await registry.load_plugins()

        tool = registry.get_tool(tool_id)
        if not tool:
            return {
                "tool_id": tool_id,
                "success": False,
                "error": f"Tool {tool_id} not found in registry",
                "status": "unknown",
            }

        # Check if already installed in persistent storage
        if await self._is_installed(tool) and self.check_persistence:
            logger.info("Tool '%s' appears to be already installed.", tool_id)

        try:
            success = await registry.install_tool(tool_id, progress_callback=progress_callback)
            # Re-fetch tool to get updated status
            tool = registry.get_tool(tool_id)

            return {
                "tool_id": tool_id,
                "success": success,
                "status": (tool.status.value if hasattr(tool.status, "value") else tool.status) if tool else "unknown",
                "error": tool.error_message if tool else None,
            }
        except (OSError, RuntimeError, ValueError) as e:
            logger.error("Installation failed for '%s': %s", tool_id, e)
            return {
                "tool_id": tool_id,
                "success": False,
                "status": "failed",
                "error": str(e),
            }

    async def uninstall(self, tool_id: str, progress_callback=None) -> dict:
        """
        Uninstall a tool by ID.

        Args:
            tool_id: The ID of the tool to uninstall.

        Returns:
            Dictionary with uninstallation result.
        """
        logger.info("Uninstalling tool '%s'", tool_id)
        registry = get_registry()

        try:
            success = await registry.uninstall_tool(tool_id, progress_callback=progress_callback)
            return {
                "tool_id": tool_id,
                "success": success,
                "status": "uninstalled" if success else "failed",
            }
        except (OSError, RuntimeError, ValueError) as e:
            logger.error("Uninstallation failed for '%s': %s", tool_id, e)
            return {
                "tool_id": tool_id,
                "success": False,
                "status": "failed",
                "error": str(e),
            }

    async def _is_installed(self, tool) -> bool:
        """
        Check if tool is actually installed on the system.

        This verifies the tool's availability by checking:
        1. If key binary is in PATH (shutil.which)
        2. OR running the verification command if configured
        """
        # 1. Check if the main command exists
        cmd_parts = tool.config.execution.command.split()
        if not cmd_parts:
            return False

        executable = cmd_parts[0]
        pass_check = shutil.which(executable) is not None

        # 2. If configured, try verification command (stronger check)
        if tool.config.installation.verification_command:
            try:
                cmd = tool.config.installation.verification_command
                logger.debug("Verifying %s with: %s", tool.config.id, cmd)

                # Run verification command with timeout
                proc = await asyncio.create_subprocess_shell(
                    cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )

                try:
                    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)

                    if proc.returncode == 0:
                        return True

                    # Some tools might return non-zero but still be installed (e.g. help output)
                    # Check if regex is provided for stricter check
                    if tool.config.installation.verification_regex:
                        import re

                        output = (stdout + stderr).decode(errors="replace")
                        if re.search(tool.config.installation.verification_regex, output):
                            return True
                        return False

                except TimeoutError:
                    logger.warning("Verification timed out for %s", tool.config.id)
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    return False

            except (OSError, RuntimeError, ValueError) as e:
                logger.warning("Verification failed for %s: %s", tool.config.id, e)
                # Fallback to shutil check if verification command fails to run
                pass

        return pass_check
