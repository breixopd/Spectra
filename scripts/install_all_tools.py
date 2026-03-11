#!/usr/bin/env python3
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.services.tools.registry import initialize_registry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("install_tools")


async def install_all_tools():
    """Install all tools defined in plugins."""
    logger.info("Initializing Tool Registry...")
    registry = await initialize_registry()

    tools = registry.list_tools()
    logger.info("Found %d tools.", len(tools))

    for tool in tools:
        logger.info("Checking tool: %s (%s)", tool.config.id, tool.config.name)

        if tool.is_available:
            logger.info("  [OK] Tool %s is already available.", tool.config.id)
            continue

        logger.info("  [INSTALL] Installing %s...", tool.config.id)
        try:
            success = await registry.install_tool(tool.config.id)
            if success:
                logger.info("  [SUCCESS] Installed %s", tool.config.id)
            else:
                logger.error(
                    "  [FAILED] Failed to install %s: %s",
                    tool.config.id,
                    tool.error_message,
                )
        except Exception as e:
            logger.error("  [ERROR] Exception installing %s: %s", tool.config.id, e)

    logger.info("Installation process complete.")


if __name__ == "__main__":
    asyncio.run(install_all_tools())
