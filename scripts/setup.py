#!/usr/bin/env python3
import asyncio
import logging
import shutil
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.services.ai.rag import EmbeddingService
from app.services.tools.registry import get_registry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("setup")


async def setup_spectra():
    """Perform initial setup for Spectra."""
    logger.info("[SETUP] Starting Spectra Setup...")

    # 1. Download Embeddings Model
    logger.info("[DOWNLOAD] Downloading embedding model (all-MiniLM-L6-v2)...")
    try:
        service = EmbeddingService()
        await service._load_model()
        logger.info("[OK] Embedding model ready.")
    except Exception as e:
        logger.error("[ERROR] Failed to download embedding model: %s", e)

    # 2. Verify Plugins
    logger.info("[PLUGINS] Verifying plugins...")
    registry = get_registry()
    await registry.load_plugins()  # Ensure plugins are loaded
    tools = registry.get_available_tools()
    logger.info("Found %d plugins: %s", len(tools), ", ".join(t.config.id for t in tools))

    # 3. Check Tool Dependencies
    logger.info("[TOOLS] Checking tool dependencies...")
    missing_tools = []
    for tool in tools:
        command = tool.config.execution.command
        if shutil.which(command):
            logger.info("  [OK] %s found", command)
        else:
            logger.warning("  [WARNING] %s NOT found in PATH", command)
            missing_tools.append(command)

    if missing_tools:
        logger.warning("Missing tools: %s", ", ".join(missing_tools))
        logger.warning("Some features may not work until these tools are installed.")
    else:
        logger.info("[OK] All tool dependencies met.")

    logger.info("[COMPLETE] Setup complete!")


if __name__ == "__main__":
    asyncio.run(setup_spectra())
