"""Worker lifecycle: startup, shutdown, golden-image status sync, heartbeat."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from spectra_tools_core.models import ToolStatus

from .helpers import _build_tool_status_payload, _is_tool_installed, _sync_tool_status

logger = logging.getLogger(__name__)


def _log_startup_banner() -> None:
    logger.info("=" * 60)
    logger.info("Spectra PostgreSQL Worker starting in tools container...")
    logger.info("=" * 60)


async def _sync_detected_tool_status(tool: object) -> bool:
    tool_id = tool.config.id
    is_installed = _is_tool_installed(tool)
    tool.status = ToolStatus.READY if is_installed else ToolStatus.PENDING

    await _sync_tool_status(tool_id, {"status": tool.status.value})

    if is_installed:
        logger.info("Tool %s already installed", tool_id)

    return is_installed


def _install_progress_callback(tool_id: str):
    async def progress_callback(update: dict[str, str]) -> None:
        await _sync_tool_status(tool_id, update)

    return progress_callback


async def _sync_install_result(tool_id: str, result: dict[str, object]) -> None:
    if result.get("success"):
        logger.info("[OK] Installed %s", tool_id)
    else:
        logger.warning("[FAIL] Failed to install %s: %s", tool_id, result.get("error"))

    await _sync_tool_status(tool_id, result)


async def _sync_install_failure(tool_id: str, error: Exception, *, unexpected: bool = False) -> None:
    if unexpected:
        logger.error("Unexpected error installing %s: %s", tool_id, error)
    else:
        logger.error("Error installing %s: %s", tool_id, error)

    await _sync_tool_status(tool_id, {"status": "failed", "error": str(error)})


async def startup() -> None:
    """Worker startup hook."""
    _log_startup_banner()

    try:
        from spectra_platform.services.tools.registry import initialize_registry

        registry = await initialize_registry(
            plugins_dir="plugins",
        )
        logger.info("Loaded %d tool plugins", len(registry.list_tools()))
    except (OSError, RuntimeError, ImportError) as e:
        logger.error("Failed to initialize registry: %s", e, exc_info=True)
        return

    await _auto_install_pending()


async def _batch_sync_tool_statuses(tools: list[object]) -> list[str]:
    """Batch sync tool statuses to cache, return list of pending tool IDs."""
    from spectra_platform.infrastructure.cache import CacheService
    from spectra_common.constants import SECONDS_PER_HOUR

    cache = CacheService()
    pending = []

    # Phase 1: Check installation status for all tools (local filesystem checks)
    for tool in tools:
        tool_id = tool.config.id
        is_installed = _is_tool_installed(tool)
        tool.status = ToolStatus.READY if is_installed else ToolStatus.PENDING

        if not is_installed:
            pending.append(tool_id)

    # Phase 2: Batch sync all statuses to cache (single batch operation)
    # Build all payloads first
    tool_statuses: dict[str, dict[str, object]] = {}
    for tool in tools:
        tool_id = tool.config.id
        result = {"status": tool.status.value}
        # Get existing status from cache (batch get would be better but requires API change)
        key = f"spectra:tool_status:{tool_id}"
        existing = await cache.get(key)
        if not isinstance(existing, dict):
            existing = {}
        payload = _build_tool_status_payload(existing, result)
        tool_statuses[key] = payload

    # Batch set all (CacheService.set doesn't support batch, but we reduce get calls)
    for key, payload in tool_statuses.items():
        await cache.set(key, payload, ttl=SECONDS_PER_HOUR)

    # Log installed tools
    for tool in tools:
        if tool.status == ToolStatus.READY:
            logger.info("Tool %s already installed", tool.config.id)

    return pending


async def _auto_install_pending() -> None:
    """Audit golden image completeness at startup.

    Checks every registered tool against the local filesystem.  Tools
    missing from the image are reported (they will trigger on-demand
    install when first used), but the worker does NOT attempt to install
    them — golden image is the delivery mechanism.
    """
    from spectra_platform.services.tools.registry import get_registry
    from spectra_worker.tool_jobs import verify_golden_image_on_startup

    registry = get_registry()
    tools = list(registry.list_tools())
    pending = await _batch_sync_tool_statuses(tools)

    if pending:
        logger.warning(
            "GOLDEN IMAGE INCOMPLETE: %d / %d tools missing (%s). "
            "Run golden_image_refresh.sh then rollout new workers. "
            "On-demand install will be used as fallback until then.",
            len(pending),
            len(tools),
            pending,
        )

    # Run the detailed audit for structured reporting
    audit = await verify_golden_image_on_startup()
    if audit["missing"]:
        logger.warning("Golden image audit: %d embedded, %d missing — rebuild needed.", len(audit["embedded"]), len(audit["missing"]))
    else:
        logger.info("Golden image audit: all %d tools pre-installed. Good.", audit["total"])


async def shutdown() -> None:
    """Worker shutdown hook — release resources."""
    logger.info("Spectra PostgreSQL Worker shutting down...")
    try:
        from spectra_platform.core.database import engine

        if engine is not None:
            await engine.dispose()
            logger.info("Database connections closed")
    except (OSError, RuntimeError) as e:
        logger.warning("Error closing database connections: %s", e)


async def heartbeat_loop(queue_name: str, interval: int = 30) -> None:
    """Periodically update the sandbox's last_heartbeat in the DB."""
    from datetime import UTC, datetime

    from sqlalchemy import update

    from spectra_platform.core.database import async_session_maker
    from spectra_platform.models.infrastructure import Sandbox

    logger.info("Starting heartbeat loop (interval=%ds, queue=%s)", interval, queue_name)
    while True:
        try:
            async with async_session_maker() as session:
                await session.execute(
                    update(Sandbox)
                    .where(Sandbox.queue_name == queue_name, Sandbox.status == "running")
                    .values(last_heartbeat=datetime.now(UTC))
                )
                await session.commit()
        except asyncio.CancelledError:
            break
        except (OSError, RuntimeError) as e:
            logger.warning("Heartbeat update failed (will retry): %s", e)
        await asyncio.sleep(interval)
