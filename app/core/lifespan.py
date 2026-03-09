"""
FastAPI Lifespan Manager.

Handles application startup and shutdown events.
Initializes database connections, cache, and other services.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI

from app.core.cache import CacheService, set_cache
from app.core.config import settings
from app.core.database import async_session_maker, engine
from app.core.events import EventType, events
from app.core.telemetry import telemetry
from app.services.ai.llm import close_global_llm_client
from app.services.system.runtime_settings import hydrate_runtime_settings_from_db
from app.services.tools.models import ToolStatus

logger = logging.getLogger("spectra.lifespan")


async def set_system_status(status: str, message: str) -> None:
    """Update system status in cache for UI polling."""
    try:
        from app.core.cache import get_cache

        cache = get_cache()
        if cache:
            await cache.set("spectra:system:status", {
                "status": status,
                "message": message,
                "timestamp": datetime.now().isoformat(),
            }, ttl=3600)
    except Exception as e:
        logger.debug("Failed to set system status: %s", e)


async def add_system_operation(op_id: str, op_type: str, desc: str) -> None:
    """Add an ongoing operation to the system status."""
    try:
        from app.core.cache import get_cache

        cache = get_cache()
        if cache:
            op = {
                "id": op_id,
                "type": op_type,
                "description": desc,
                "started_at": datetime.now().isoformat(),
            }
            await cache.set(f"spectra:system:operations:{op_id}", op, ttl=3600)
    except Exception as e:
        logger.debug("Failed to add system operation: %s", e)


async def remove_system_operation(op_id: str) -> None:
    """Remove a completed operation."""
    try:
        from app.core.cache import get_cache

        cache = get_cache()
        if cache:
            await cache.delete(f"spectra:system:operations:{op_id}")
    except Exception as e:
        logger.debug("Failed to remove system operation: %s", e)


async def _mark_all_tools_ready() -> None:
    """Mark all registered tools as ready in cache.

    Used as a fallback when the tools worker is not available.
    """
    try:
        from app.core.cache import get_cache
        from app.services.tools.registry import get_registry

        cache = get_cache()
        registry = get_registry()
        tools = registry.list_tools()
        for tool in tools:
            key = f"spectra:tool_status:{tool.config.id}"
            if cache:
                await cache.set(key, {"status": "ready"}, ttl=3600)
            tool.status = ToolStatus.READY

        logger.info("Marked %d tools as ready (no worker)", len(tools))
    except Exception as e:
        logger.warning("Failed to mark tools as ready: %s", e)


async def run_startup_tasks() -> None:
    """Run background tasks on startup."""
    try:
        logger.info("Running startup tasks...")

        await add_system_operation(
            "tool_install", "install", "Installing security tools"
        )

        # Mark tools as ready immediately so the UI works.
        # If the tools worker (Kali container) is running, it will update
        # statuses to reflect actual installation state.
        await _mark_all_tools_ready()

        try:
            from app.core.queue import PostgresJobQueue

            queue = PostgresJobQueue()
            await queue.enqueue_job("install_all_tools_job")
            logger.info("Queued tool installation job via PostgresJobQueue")
        except Exception as e:
            logger.debug("Could not queue install job (tools worker may not be running): %s", e)

        await remove_system_operation("tool_install")
        await set_system_status("ready", "System ready")
        logger.info("Startup tasks completed")

    except Exception as e:
        logger.warning("Startup tasks failed: %s", e)
        await set_system_status("ready", "System ready (some tasks skipped)")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.

    Startup:
        - Initialize cache service
        - Initialize database tables
        - Load plugins and install tools
        - Load AI models (if local)
        - Run background setup tasks

    Shutdown:
        - Dispose database engine
        - Close LLM client
    """
    logger.info("[STARTUP] Starting Spectra...")

    # --- Startup ---
    try:
        # Initialize cache service (PostgreSQL-backed)
        cache = CacheService()
        set_cache(cache)
        logger.info("[OK] Cache service initialized")

        # Set initial system status
        await set_system_status("initializing", "Connecting services...")

        # Database migrations are handled by start.sh before uvicorn starts
        telemetry.update_service_status("database", healthy=True)
        logger.info("[OK] Database ready (migrations handled by start script)")

        # Store session maker in app state for dependency injection
        app.state.db_session_maker = async_session_maker

        await hydrate_runtime_settings_from_db(persist_normalized=True, commit=True)
        logger.info("[OK] Runtime settings hydrated from DB")

        await set_system_status("initializing", "Loading AI models...")

        # Preload embedding model in background (for RAG)
        try:
            from app.services.ai.embeddings import EmbeddingService

            await add_system_operation(
                "embeddings", "load", "Loading embedding model"
            )
            embed_service = EmbeddingService()

            async def load_embeddings_with_status():
                try:
                    await embed_service._load_model()
                    logger.info("[OK] Embedding model loaded")
                except Exception as e:
                    logger.warning("Embedding model loading failed: %s", e)
                finally:
                    await remove_system_operation("embeddings")

            asyncio.create_task(load_embeddings_with_status())
            logger.info("Triggered embedding model preloading")
        except Exception as e:
            logger.warning("Failed to trigger embedding preloading: %s", e)

        await set_system_status("initializing", "Loading tool plugins...")

        # Initialize tool registry and load plugins
        try:
            from app.services.tools.registry import initialize_registry

            registry = await initialize_registry(
                plugins_dir="plugins",
                public_key_path="keys/plugin_signing.pub",
                safe_mode=settings.PLUGIN_SAFE_MODE,
            )
            tool_count = len(registry.list_tools())
            logger.info("[OK] Tool registry initialized: %d tools loaded", tool_count)
        except Exception as e:
            logger.error("Failed to initialize tool registry: %s", e)

        await set_system_status("initializing", "Installing tools...")

        # Trigger background setup tasks (including tool installation)
        asyncio.create_task(run_startup_tasks())

        # Emit startup event
        await events.emit(
            EventType.SERVICE_HEALTH_CHANGED,
            source="lifespan",
            service="spectra",
            status="started",
        )

        logger.info("[READY] Spectra is ready!")

        # Start event-to-websocket bridge
        try:
            from app.core.bridge import EventWebSocketBridge
            _event_bridge = EventWebSocketBridge()
            _event_bridge.start()
            logger.info("[OK] Event bridge started")
        except Exception as e:
            logger.warning("Failed to start event bridge: %s", e)
            _event_bridge = None

    except Exception as e:
        logger.error("[ERROR] Startup failed: %s", e)
        raise

    yield  # Application is running

    # --- Shutdown ---
    logger.info("[SHUTDOWN] Shutting down Spectra...")

    try:
        # Cancel background tasks
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if tasks:
            logger.info("Cancelling %d outstanding tasks...", len(tasks))
            for task in tasks:
                task.cancel()

            # Wait for tasks to cancel with timeout
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True), timeout=5.0
                )
            except TimeoutError:
                logger.warning("Timed out waiting for tasks to cancel")

        # Close LLM Client
        await close_global_llm_client()
        logger.info("[OK] LLM client closed")

        # Stop event bridge
        try:
            if '_event_bridge' in dir() and _event_bridge:
                _event_bridge.stop()
                logger.info("[OK] Event bridge stopped")
        except Exception as e:
            logger.debug("Event bridge stop failed: %s", e)

        # Dispose database engine
        await engine.dispose()
        logger.info("[OK] Database connections closed")

    except Exception as e:
        logger.error("[ERROR] Shutdown error: %s", e)

    logger.info("[STOPPED] Spectra stopped.")
