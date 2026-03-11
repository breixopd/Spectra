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
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import SecretStr

from app.core.cache import CacheService, set_cache
from app.core.config import settings
from app.core.database import async_session_maker, engine
from app.core.events import EventType, events
from app.core.telemetry import telemetry
from app.services.ai.llm import close_global_llm_client
from app.services.system.runtime_settings import hydrate_runtime_settings_from_db
from app.services.tools.models import ToolStatus

logger = logging.getLogger("spectra.lifespan")

# Interval for cache cleanup (seconds) — every 10 minutes
_CACHE_CLEANUP_INTERVAL = 600


async def cache_cleanup_loop() -> None:
    """Periodically purge expired cache entries."""
    from app.core.cache import get_cache

    logger.info("Cache cleanup task started (interval=%ds)", _CACHE_CLEANUP_INTERVAL)
    while True:
        try:
            await asyncio.sleep(_CACHE_CLEANUP_INTERVAL)
            cache = get_cache()
            if cache:
                removed = await cache.purge_expired()
                if removed:
                    logger.info("Cache cleanup: purged %d expired entries", removed)
        except asyncio.CancelledError:
            logger.info("Cache cleanup task stopped")
            break
        except Exception as e:
            logger.error("Cache cleanup error: %s", e)


async def sandbox_watchdog_loop() -> None:
    """Periodically check sandbox heartbeats and reap stale ones."""
    from datetime import UTC, datetime

    from sqlalchemy import select

    from app.models.infrastructure import Sandbox
    from app.services.tools.sandbox import get_sandbox_pool

    logger.info("Sandbox watchdog started (idle_timeout=%ds)", settings.SANDBOX_IDLE_TIMEOUT)
    while True:
        try:
            await asyncio.sleep(60)
            pool = get_sandbox_pool()
            if not pool or not pool.available:
                continue

            async with async_session_maker() as session:
                result = await session.execute(
                    select(Sandbox).where(Sandbox.status == "running")
                )
                sandboxes = list(result.scalars().all())

            now = datetime.now(UTC)
            for sb in sandboxes:
                age = (now - sb.created_at).total_seconds()
                if age < settings.SANDBOX_HEARTBEAT_INTERVAL * 2:
                    continue

                if sb.last_heartbeat:
                    idle_seconds = (now - sb.last_heartbeat).total_seconds()
                else:
                    idle_seconds = age

                if idle_seconds > settings.SANDBOX_IDLE_TIMEOUT:
                    logger.warning(
                        "Watchdog: reaping stale sandbox %s (mission=%s, idle=%.0fs)",
                        sb.container_name, sb.mission_id[:8], idle_seconds,
                    )
                    await pool.destroy(sb.mission_id)

        except asyncio.CancelledError:
            logger.info("Sandbox watchdog stopped")
            break
        except Exception as e:
            logger.error("Sandbox watchdog error: %s", e)


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


async def seed_default_plans() -> None:
    """Create default plans if none exist."""
    try:
        from sqlalchemy import func, select

        from app.models.plan import Plan

        async with async_session_maker() as session:
            result = await session.execute(select(func.count(Plan.id)))
            count = result.scalar() or 0
            if count > 0:
                return

            default_plans = [
                Plan(
                    name="free",
                    display_name="Free",
                    description="Get started with basic manual security testing",
                    is_default=True,
                    sort_order=0,
                    max_concurrent_missions=1,
                    max_missions_per_month=5,
                    max_targets=10,
                    sandbox_max_containers=1,
                    sandbox_resource_tier="small",
                    max_storage_mb=100,
                    max_api_requests_per_hour=50,
                    max_api_requests_per_day=200,
                    features={
                        "autonomous_mode": False,
                        "manual_mode": True,
                        "report_export": ["json"],
                        "custom_wordlists": False,
                        "pipeline_builder": False,
                        "cve_browser": True,
                        "shell_access": False,
                        "api_access": False,
                        "vpn_support": False,
                        "advanced_reporting": False,
                    },
                ),
                Plan(
                    name="starter",
                    display_name="Starter",
                    description="For individual security researchers and bug bounty hunters",
                    is_default=False,
                    sort_order=1,
                    max_concurrent_missions=2,
                    max_missions_per_month=25,
                    max_targets=50,
                    sandbox_max_containers=1,
                    sandbox_resource_tier="medium",
                    max_storage_mb=500,
                    max_api_requests_per_hour=100,
                    max_api_requests_per_day=1000,
                    features={
                        "autonomous_mode": True,
                        "manual_mode": True,
                        "report_export": ["json", "pdf", "html"],
                        "custom_wordlists": True,
                        "pipeline_builder": False,
                        "cve_browser": True,
                        "shell_access": True,
                        "api_access": False,
                        "vpn_support": False,
                        "advanced_reporting": False,
                    },
                ),
                Plan(
                    name="professional",
                    display_name="Professional",
                    description="Full-featured assessments for professional pentesters and consultancies",
                    is_default=False,
                    sort_order=2,
                    max_concurrent_missions=5,
                    max_missions_per_month=None,
                    max_targets=500,
                    sandbox_max_containers=3,
                    sandbox_resource_tier="large",
                    max_storage_mb=5000,
                    max_api_requests_per_hour=500,
                    max_api_requests_per_day=5000,
                    features={
                        "autonomous_mode": True,
                        "manual_mode": True,
                        "report_export": ["json", "pdf", "html"],
                        "custom_wordlists": True,
                        "pipeline_builder": True,
                        "cve_browser": True,
                        "shell_access": True,
                        "api_access": True,
                        "vpn_support": True,
                        "advanced_reporting": True,
                    },
                ),
                Plan(
                    name="enterprise",
                    display_name="Enterprise",
                    description="Unlimited access for security teams and large organizations",
                    is_default=False,
                    sort_order=3,
                    max_concurrent_missions=999,
                    max_missions_per_month=None,
                    max_targets=None,
                    sandbox_max_containers=10,
                    sandbox_resource_tier="xlarge",
                    max_storage_mb=50000,
                    max_api_requests_per_hour=5000,
                    max_api_requests_per_day=50000,
                    features={
                        "autonomous_mode": True,
                        "manual_mode": True,
                        "report_export": ["json", "pdf", "html"],
                        "custom_wordlists": True,
                        "pipeline_builder": True,
                        "cve_browser": True,
                        "shell_access": True,
                        "api_access": True,
                        "vpn_support": True,
                        "advanced_reporting": True,
                        "team_sharing": True,
                    },
                ),
            ]
            session.add_all(default_plans)
            await session.commit()
            logger.info("Created %d default plans", len(default_plans))
    except Exception as e:
        logger.warning("Failed to seed default plans: %s", e)


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
    except Exception as e:
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
    except Exception as e:
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
    except Exception as e:
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

    # --- Security: validate secret keys in production ---
    if not settings.DEBUG:
        _insecure_defaults = {"", "change-me-in-production"}
        jwt_val = settings.JWT_SECRET_KEY.get_secret_value()
        secret_val = settings.SECRET_KEY.get_secret_value() if isinstance(settings.SECRET_KEY, SecretStr) else str(settings.SECRET_KEY)
        if jwt_val in _insecure_defaults:
            raise RuntimeError(
                "JWT_SECRET_KEY is empty or using a default value. "
                "Set a strong secret via the JWT_SECRET_KEY environment variable before running in production."
            )
        if secret_val in _insecure_defaults:
            raise RuntimeError(
                "SECRET_KEY is empty or using the default 'change-me-in-production'. "
                "Set a strong secret via the SECRET_KEY environment variable before running in production."
            )

    # --- Startup ---
    try:
        # Initialize storage service (S3 or local)
        from app.services.storage import close_storage_service, get_storage_service
        storage = get_storage_service()
        logger.info("[OK] Storage service initialized (mode: %s)", "s3" if storage.is_s3 else "local")
        # Initialize cache service (PostgreSQL-backed)
        cache = CacheService()
        set_cache(cache)
        logger.info("[OK] Cache service initialized")

        # Set initial system status
        await set_system_status("initializing", "Connecting services...")

        # Database migrations are handled by start.sh before uvicorn starts
        telemetry.update_service_status("database", healthy=True)
        logger.info("[OK] Database ready (migrations handled by start script)")

        # Run startup checks (informational, non-blocking)
        await run_startup_checks()

        # Store session maker in app state for dependency injection
        app.state.db_session_maker = async_session_maker

        await hydrate_runtime_settings_from_db(persist_normalized=True, commit=True)
        logger.info("[OK] Runtime settings hydrated from DB")

        # Seed default plans if none exist
        await seed_default_plans()

        # Initialize service registry
        from app.services.gateway.service_registry import get_service_registry
        get_service_registry()
        logger.info("[OK] Service registry initialized")

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

        # Initialize sandbox pool
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
                            except Exception as e:
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
        except Exception as e:
            logger.warning("Sandbox pool init failed: %s", e)

        # Initialize server pool manager
        try:
            from app.services.scaling import get_pool_manager
            pool_mgr = get_pool_manager()
            await pool_mgr.start_health_loop()
            logger.info("[OK] Server pool manager initialized")
        except Exception as e:
            logger.warning("Server pool manager init failed: %s", e)

        # Trigger background setup tasks (including tool installation)
        asyncio.create_task(run_startup_tasks())

        # Start periodic cache cleanup
        asyncio.create_task(cache_cleanup_loop())

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
    # Close storage service
    try:
        from app.services.storage import close_storage_service
        await close_storage_service()
        logger.info("[OK] Storage service closed")
    except Exception as e:
        logger.warning("Storage service close error: %s", e)
    logger.info("[SHUTDOWN] Shutting down Spectra...")

    # Stop server pool health loop
    try:
        from app.services.scaling import get_pool_manager
        pool_mgr = get_pool_manager()
        await pool_mgr.stop_health_loop()
    except Exception as e:
        logger.warning("Server pool shutdown error: %s", e)

    # Clean up warm pool first
    try:
        from app.services.tools.sandbox import get_warm_pool_manager
        wm = get_warm_pool_manager()
        if wm:
            await wm.cleanup()
    except Exception as e:
        logger.warning("Warm pool cleanup error: %s", e)

    # Clean up sandbox containers (before cancelling tasks)
    try:
        from app.services.tools.sandbox import get_sandbox_pool

        pool = get_sandbox_pool()
        if pool and pool.available:
            cleaned = await pool.cleanup_all()
            logger.info("[OK] Cleaned up %d sandbox containers", cleaned)
    except Exception as e:
        logger.warning("Sandbox cleanup error: %s", e)

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

        # Close service registry (all gateway connections)
        from app.services.gateway.service_registry import close_service_registry
        await close_service_registry()
        logger.info("[OK] Service registry closed")

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
