#!/usr/bin/env python3
# ⚠ DEPRECATED — The app now indexes tool documentation on startup
# and when plugins are installed/updated. Use this only for manual re-indexing.
"""
Tool Documentation Indexer.

Runs tools with --help to generate documentation and indexes it for RAG.
"""

import asyncio
import logging
import shlex
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from app.services.ai.rag import Document
from app.services.tools.registry import get_registry
from scripts import init_script_services

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("spectra.scripts.index_tool_docs")


async def main():
    """Main indexing loop."""
    logger.info("Starting tool documentation indexing...")

    # Initialize common services
    rag = await init_script_services()

    # Get Registry
    registry = get_registry()
    tools = registry.get_available_tools()

    logger.info("Found %d tools to index.", len(tools))

    for tool in tools:
        logger.info("Indexing %s...", tool.config.id)

        try:
            cmd_parts = shlex.split(tool.config.execution.command)
            proc = await asyncio.create_subprocess_exec(
                *cmd_parts, "--help",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            output = stdout.decode() + stderr.decode()

            if not output.strip():
                logger.warning("No output for %s", tool.config.id)
                continue

            # Create document
            doc_text = f"Tool: {tool.config.name}\nDescription: {tool.config.description}\n\nUsage:\n{output}"

            doc = Document(
                id=f"tool_doc_{tool.config.id}",
                content=doc_text,
                doc_type="tool_doc",
                metadata={
                    "tool_id": tool.config.id,
                    "category": tool.config.category,
                    "source": "help_output",
                },
            )

            await rag.index_document(doc)
            logger.info("Indexed %s", tool.config.id)

        except Exception as e:
            logger.error("Failed to index %s: %s", tool.config.id, e)

    logger.info("Tool indexing complete.")


if __name__ == "__main__":
    asyncio.run(main())
