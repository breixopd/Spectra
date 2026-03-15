"""
FastAPI Lifespan Manager.

Handles application startup and shutdown events.
Initializes database connections, cache, and other services.
"""

import asyncio
import logging
import shutil
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import SecretStr

try:
    from docker.errors import DockerException
except ImportError:
    DockerException = OSError  # Fallback when docker SDK not installed

from app.core.background_tasks import (
    cache_cleanup_loop,
    periodic_cleanup_loop,
    sandbox_watchdog_loop,
)
from app.core.cache import CacheService, set_cache
from app.core.config import settings
from app.core.database import async_session_maker, engine
from sqlalchemy.exc import SQLAlchemyError
from app.core.events import EventType, events
from app.core.system_status import (
    add_system_operation,
    remove_system_operation,
    set_system_status,
)
from app.core.telemetry import telemetry
from app.services.ai.llm import close_global_llm_client
from app.services.system.runtime_settings import hydrate_runtime_settings_from_db
from app.services.tools.models import ToolStatus

logger = logging.getLogger(__name__)


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
    except (OSError, RuntimeError, ImportError) as e:
        logger.warning("Failed to mark tools as ready: %s", e)


from app.services.billing.seed_plans import seed_default_plans  # noqa: E402


async def run_startup_checks() -> None:
    """Run pre-flight checks and log results. Warns but does not block startup."""
    logger.info("[CHECK] Running startup checks...")

    # 1. Database connectivity
    try:
        from sqlalchemy import text

        async with async_session_maker() as session:
            result = await asyncio.wait_for(
                session.execute(text("SELECT 1")),
                timeout=10.0,
            )
            result.scalar()
        logger.info("[CHECK][OK] Database connectivity verified")
    except TimeoutError:
        logger.warning("[CHECK][WARN] Database connectivity check timed out (10s)")
    except (OSError, RuntimeError, SQLAlchemyError) as e:
        logger.warning("[CHECK][WARN] Database connectivity check failed: %s", e)

    # 2. Required tables existence
    try:
        from sqlalchemy import text as sa_text

        expected_tables = {"users", "missions", "targets", "findings", "exploits"}
        async with async_session_maker() as session:
            result = await session.execute(
                sa_text(
                    "SELECT tablename FROM pg_catalog.pg_tables "
                    "WHERE schemaname = 'public'"
                )
            )
            existing = {row[0] for row in result.fetchall()}

        missing = expected_tables - existing
        if missing:
            logger.warning("[CHECK][WARN] Missing database tables: %s", ", ".join(sorted(missing)))
        else:
            logger.info("[CHECK][OK] All expected tables present")
    except (OSError, RuntimeError, SQLAlchemyError) as e:
        logger.warning("[CHECK][WARN] Table existence check failed: %s", e)

    # 3. Disk space for data directory
    try:
        data_dir = Path("data")
        data_dir.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(str(data_dir))
        free_mb = usage.free / (1024 * 1024)
        if free_mb < 100:
            logger.warning(
                "[CHECK][WARN] Low disk space for data directory: %.0f MB free", free_mb
            )
        else:
            logger.info("[CHECK][OK] Disk space: %.0f MB free", free_mb)
    except (OSError, RuntimeError, ConnectionError) as e:
        logger.warning("[CHECK][WARN] Disk space check failed: %s", e)

    logger.info("[CHECK] Startup checks complete")


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
        except (OSError, RuntimeError, ImportError) as e:
            logger.debug("Could not queue install job (tools worker may not be running): %s", e)

        await remove_system_operation("tool_install")
        await set_system_status("ready", "System ready")
        logger.info("Startup tasks completed")

    except (OSError, RuntimeError, ImportError) as e:
        logger.warning("Startup tasks failed: %s", e)
        await set_system_status("ready", "System ready (some tasks skipped)")


def _validate_production_secrets() -> None:
    """Validate secret keys are not using insecure defaults in production."""
    if settings.DEBUG:
        return

    _insecure_defaults = {
        "", "change-me-in-production", "test-key", "secret",
        "changeme", "password", "default",
    }
    jwt_val = settings.JWT_SECRET_KEY.get_secret_value()
    secret_val = settings.SECRET_KEY.get_secret_value() if isinstance(settings.SECRET_KEY, SecretStr) else str(settings.SECRET_KEY)
    if jwt_val.lower() in _insecure_defaults:
        raise RuntimeError(
            "JWT_SECRET_KEY is empty or using a default value. "
            "Set a strong secret via the JWT_SECRET_KEY environment variable before running in production."
        )
    if len(jwt_val) < 32:
        logger.warning(
            "[SECURITY] JWT_SECRET_KEY is shorter than 32 characters. "
            "Use a longer secret for production security."
        )
    if secret_val.lower() in _insecure_defaults:
        raise RuntimeError(
            "SECRET_KEY is empty or using the default 'change-me-in-production'. "
            "Set a strong secret via the SECRET_KEY environment variable before running in production."
        )
    db_url = str(settings.DATABASE_URL)
    if "sqlite" in db_url.lower():
        logger.warning(
            "[SECURITY] DATABASE_URL uses SQLite, which is not suitable for production. "
            "Configure a PostgreSQL connection string."
        )


async def _initialize_database(app: FastAPI) -> None:
    """Verify database connectivity, hydrate settings, and store session maker."""
    from app.services.storage import get_storage_service

    storage = get_storage_service()
    logger.info("[OK] Storage service initialized (mode: %s)", "s3" if storage.is_s3 else "local")

    cache = CacheService()
    set_cache(cache)
    logger.info("[OK] Cache service initialized")

    await set_system_status("initializing", "Connecting services...")

    telemetry.update_service_status("database", healthy=True)
    logger.info("[OK] Database ready (migrations handled by start script)")

    await run_startup_checks()

    app.state.db_session_maker = async_session_maker

    await hydrate_runtime_settings_from_db(persist_normalized=True, commit=True)
    logger.info("[OK] Runtime settings hydrated from DB")


async def _seed_default_data() -> None:
    """Seed plans and other default data if not present."""
    await seed_default_plans()

    from app.services.gateway.service_registry import get_service_registry
    get_service_registry()
    logger.info("[OK] Service registry initialized")


async def _initialize_sandbox() -> None:
    """Initialize sandbox pool, warm pool manager, and golden image builder."""
    try:
        from app.services.tools.sandbox import SandboxPool, set_sandbox_pool

        sandbox_pool = SandboxPool()
        set_sandbox_pool(sandbox_pool)
        if sandbox_pool.available:
            orphans = await sandbox_pool.cleanup_all()
            if orphans:
                logger.info("[OK] Cleaned %d orphaned sandbox containers", orphans)
            logger.info("[OK] Sandbox pool initialized")
            asyncio.create_task(sandbox_watchdog_loop())
            logger.info("[OK] Sandbox watchdog started")

            # Initialize warm pool manager
            if settings.SANDBOX_WARM_POOL_ENABLED:
                from app.services.tools.sandbox import WarmPoolManager, set_warm_pool_manager
                warm_manager = WarmPoolManager(sandbox_pool)
                set_warm_pool_manager(warm_manager)

                async def warm_pool_maintain_loop():
                    while True:
                        try:
                            await asyncio.sleep(30)
                            await warm_manager.maintain()
                        except asyncio.CancelledError:
                            break
                        except (OSError, RuntimeError) as e:
                            logger.error("Warm pool maintain error: %s", e)

                asyncio.create_task(warm_pool_maintain_loop())
                asyncio.create_task(warm_manager.maintain())
                logger.info("[OK] Warm pool manager initialized (size=%d)", settings.SANDBOX_WARM_POOL_SIZE)

            # Initialize golden image builder
            if settings.SANDBOX_AUTO_BUILD_IMAGE:
                from app.services.tools.sandbox import GoldenImageBuilder, set_image_builder

                builder = GoldenImageBuilder()
                set_image_builder(builder)

                async def on_plugin_change(**kwargs: Any) -> None:
                    """Trigger golden image rebuild when plugins change."""
                    asyncio.create_task(builder.build())

                events.subscribe(EventType.PLUGIN_UPDATED, on_plugin_change)
                logger.info("[OK] Golden image builder initialized (auto-build on plugin changes)")
        else:
            logger.warning("[WARN] Sandbox pool unavailable — Docker not accessible")
    except (DockerException, OSError) as e:
        logger.warning("Sandbox pool init failed: %s", e)


async def _initialize_scaling() -> None:
    """Initialize server pool manager and start health loop."""
    try:
        from app.services.scaling import get_pool_manager
        pool_mgr = get_pool_manager()
        await pool_mgr.start_health_loop()
        logger.info("[OK] Server pool manager initialized")
    except (OSError, RuntimeError, ImportError) as e:
        logger.warning("Server pool manager init failed: %s", e)


async def _initialize_services() -> None:
    """Start background services: AI models, tool registry, sandboxes, etc."""
    await set_system_status("initializing", "Loading AI models...")

    # Preload embedding model in background (for RAG)
    try:
        from app.services.ai.embeddings import EmbeddingService

        await add_system_operation("embeddings", "load", "Loading embedding model")
        embed_service = EmbeddingService()

        async def load_embeddings_with_status():
            try:
                await embed_service._load_model()
                logger.info("[OK] Embedding model loaded")
            except (OSError, RuntimeError, ImportError) as e:
                logger.warning("Embedding model loading failed: %s", e)
            finally:
                await remove_system_operation("embeddings")

        asyncio.create_task(load_embeddings_with_status())
        logger.info("Triggered embedding model preloading")
    except (OSError, RuntimeError, ImportError) as e:
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
    except (OSError, ValueError, KeyError) as e:
        logger.error("Failed to initialize tool registry: %s", e)

    await set_system_status("initializing", "Installing tools...")

    # Initialize sandbox pool
    await _initialize_sandbox()

    # Initialize server pool manager
    await _initialize_scaling()

    # Trigger background setup tasks (including tool installation)
    asyncio.create_task(run_startup_tasks())

    # Start periodic cache cleanup
    asyncio.create_task(cache_cleanup_loop())

    # Start periodic system cleanup (sessions, old jobs, orphaned sandboxes)
    asyncio.create_task(periodic_cleanup_loop())

    # Start metrics snapshot store
    from app.core.metrics_store import get_metrics_store
    metrics_store = get_metrics_store()
    await metrics_store.start()
    logger.info("[OK] Metrics store started")

    # Emit startup event
    await events.emit(
        EventType.SERVICE_HEALTH_CHANGED,
        source="lifespan",
        service="spectra",
        status="started",
    )


async def _start_event_bridge() -> Any | None:
    """Start the event-to-websocket bridge. Returns the bridge instance or None."""
    try:
        from app.core.bridge import EventWebSocketBridge
        bridge = EventWebSocketBridge()
        bridge.start()
        logger.info("[OK] Event bridge started")
        return bridge
    except (OSError, RuntimeError, ImportError) as e:
        logger.warning("Failed to start event bridge: %s", e)
        return None


async def _shutdown_services() -> None:
    """Gracefully shut down all services."""
    # Close storage service
    try:
        from app.services.storage import close_storage_service
        await close_storage_service()
        logger.info("[OK] Storage service closed")
    except (OSError, RuntimeError) as e:
        logger.warning("Storage service close error: %s", e)

    logger.info("[SHUTDOWN] Shutting down Spectra...")

    # Stop server pool health loop
    try:
        from app.services.scaling import get_pool_manager
        pool_mgr = get_pool_manager()
        await pool_mgr.stop_health_loop()
    except (OSError, RuntimeError) as e:
        logger.warning("Server pool shutdown error: %s", e)

    # Clean up warm pool first
    try:
        from app.services.tools.sandbox import get_warm_pool_manager
        wm = get_warm_pool_manager()
        if wm:
            await wm.cleanup()
    except (OSError, RuntimeError) as e:
        logger.warning("Warm pool cleanup error: %s", e)

    # Clean up sandbox containers (before cancelling tasks)
    try:
        from app.services.tools.sandbox import get_sandbox_pool

        pool = get_sandbox_pool()
        if pool and pool.available:
            cleaned = await pool.cleanup_all()
            logger.info("[OK] Cleaned up %d sandbox containers", cleaned)
    except (OSError, RuntimeError) as e:
        logger.warning("Sandbox cleanup error: %s", e)

    try:
        # Cancel background tasks
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if tasks:
            logger.info("Cancelling %d outstanding tasks...", len(tasks))
            for task in tasks:
                task.cancel()

            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True), timeout=5.0
                )
            except TimeoutError:
                logger.warning("Timed out waiting for tasks to cancel")

        # Close service registry (all gateway connections)
        from app.services.gateway.service_registry import close_service_registry
        await close_service_registry()
        logger.info("[OK] Service registry closed")

        # Close LLM Client
        await close_global_llm_client()
        logger.info("[OK] LLM client closed")

        # Dispose database engine
        await engine.dispose()
        logger.info("[OK] Database connections closed")

    except (OSError, RuntimeError) as e:
        logger.error("[ERROR] Shutdown error: %s", e)

    logger.info("[STOPPED] Spectra stopped.")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager — delegates to focused sub-functions."""
    logger.info("[STARTUP] Starting Spectra...")

    _validate_production_secrets()

    try:
        await _initialize_database(app)
        await _seed_default_data()
        await _initialize_services()
        logger.info("[READY] Spectra is ready!")
        _event_bridge = await _start_event_bridge()
    except (OSError, RuntimeError, ImportError) as e:
        logger.error("[ERROR] Startup failed: %s", e)
        raise

    yield

    if _event_bridge:
        try:
            _event_bridge.stop()
            logger.info("[OK] Event bridge stopped")
        except (OSError, RuntimeError) as e:
            logger.debug("Event bridge stop failed: %s", e)

    await _shutdown_services()
