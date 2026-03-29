"""Worker lifecycle: startup, shutdown, auto-install, heartbeat."""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.services.tools.models import ToolStatus

from .helpers import _is_tool_installed, _sync_tool_status

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
        from app.services.tools.registry import initialize_registry

        registry = await initialize_registry(
            plugins_dir="plugins",
            public_key_path="keys/plugin_signing.pub",
            safe_mode=settings.PLUGIN_SAFE_MODE,
        )
        logger.info("Loaded %d tool plugins", len(registry.list_tools()))
    except (OSError, RuntimeError, ImportError) as e:
        logger.error("Failed to initialize registry: %s", e, exc_info=True)
        return

    await _auto_install_pending()


async def _auto_install_pending() -> None:
    """Auto-install pending tools on startup."""
    from app.services.tools.installer import ToolInstaller
    from app.services.tools.registry import get_registry

    registry = get_registry()
    pending = []
    for tool in registry.list_tools():
        if not await _sync_detected_tool_status(tool):
            pending.append(tool.config.id)

    if pending:
        logger.info("Auto-installing %d tools: %s", len(pending), pending)
        installer = ToolInstaller()
        for tool_id in pending:
            try:
                result = await installer.install(
                    tool_id,
                    progress_callback=_install_progress_callback(tool_id),
                )
                await _sync_install_result(tool_id, result)
            except (OSError, RuntimeError, ValueError) as e:
                await _sync_install_failure(tool_id, e)
            except Exception as e:  # noqa: BLE001 – unknown plugin errors must not crash worker
                await _sync_install_failure(tool_id, e, unexpected=True)


async def shutdown() -> None:
    """Worker shutdown hook — release resources."""
    logger.info("Spectra PostgreSQL Worker shutting down...")
    try:
        from app.core.database import engine

        await engine.dispose()
        logger.info("Database connections closed")
    except (OSError, RuntimeError) as e:
        logger.warning("Error closing database connections: %s", e)


async def heartbeat_loop(queue_name: str, interval: int = 30) -> None:
    """Periodically update the sandbox's last_heartbeat in the DB."""
    from datetime import UTC, datetime

    from sqlalchemy import update

    from app.core.database import async_session_maker
    from app.models.infrastructure import Sandbox

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
            logger.debug("Heartbeat update failed: %s", e)
        await asyncio.sleep(interval)
