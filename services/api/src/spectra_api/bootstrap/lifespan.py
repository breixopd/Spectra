"""
FastAPI Lifespan Manager.

Handles application startup and shutdown events.
Initializes database connections, cache, and other services.
"""

import asyncio
import logging
import shutil
import socket
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI
from pydantic import SecretStr

try:
    from docker.errors import DockerException
except ImportError:
    DockerException = OSError  # Fallback when docker SDK not installed

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.database import async_session_maker, engine
from app.infrastructure.cache import CacheService, set_cache
from app.infrastructure.events import EventType, events
from app.infrastructure.system_status import (
    add_system_operation,
    remove_system_operation,
    set_system_status,
)
from app.services.billing.seed_plans import seed_default_plans
from app.services.system.runtime_settings import hydrate_runtime_settings_from_db
from app.telemetry.telemetry import telemetry
from spectra_common.advisory_locks import stable_lock_id
from spectra_common.paths import data_root
from spectra_common.tasks import create_safe_task

logger = logging.getLogger(__name__)


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
                sa_text("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'")
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
        data_dir = data_root()
        data_dir.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(str(data_dir))
        free_mb = usage.free / (1024 * 1024)
        if free_mb < 100:
            logger.warning("[CHECK][WARN] Low disk space for data directory: %.0f MB free", free_mb)
        else:
            logger.info("[CHECK][OK] Disk space: %.0f MB free", free_mb)
    except (OSError, RuntimeError, ConnectionError) as e:
        logger.warning("[CHECK][WARN] Disk space check failed: %s", e)

    logger.info("[CHECK] Startup checks complete")


async def run_startup_tasks() -> None:
    """Run background tasks on startup."""
    try:
        logger.info("Running startup tasks...")

        await set_system_status("ready", "System ready")
        logger.info("Startup tasks completed")

    except (OSError, RuntimeError, ImportError) as e:
        logger.warning("Startup tasks failed: %s", e)
        await set_system_status("ready", "System ready (some tasks skipped)")


def _validate_noop_payment() -> None:
    """Prevent accidentally running with the noop (free-access) payment adapter in production."""
    if settings.DEBUG:
        return
    if not settings.PLATFORM_EXPOSED:
        return
    if settings.PAYMENT_PROVIDER.lower() == "noop":
        raise RuntimeError(
            "PAYMENT_PROVIDER is set to 'noop' but PLATFORM_EXPOSED is True. "
            "All users would receive unlimited free access. "
            "Configure a real payment provider (stripe, crypto, or manual) "
            "or set PLATFORM_EXPOSED=false for internal deployments."
        )


def _validate_stripe_webhook_secret() -> None:
    """Require a webhook signing secret when Stripe is the active payment provider."""
    if settings.PAYMENT_PROVIDER.strip().lower() != "stripe":
        return

    stripe_secret = settings.STRIPE_SECRET_KEY.get_secret_value().strip()
    webhook_secret = settings.STRIPE_WEBHOOK_SECRET.get_secret_value().strip()
    if not stripe_secret or webhook_secret:
        return

    logger.error(
        "[SECURITY] PAYMENT_PROVIDER is 'stripe' and STRIPE_SECRET_KEY is configured, "
        "but STRIPE_WEBHOOK_SECRET is empty. Refusing startup because webhook signatures "
        "cannot be verified."
    )
    raise RuntimeError(
        "STRIPE_WEBHOOK_SECRET must be set when PAYMENT_PROVIDER='stripe' and STRIPE_SECRET_KEY is configured"
    )


def _validate_rate_limit_storage() -> None:
    storage_uri = settings.RATE_LIMIT_STORAGE.strip()
    if not storage_uri.startswith(("redis://", "rediss://")):
        return

    parsed = urlparse(storage_uri)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    try:
        with socket.create_connection((host, port), timeout=2.0):
            logger.info("[OK] Rate-limit storage reachable at %s:%s", host, port)
    except OSError as exc:
        logger.error(
            "[SECURITY] RATE_LIMIT_STORAGE points to Redis at %s:%s but it is unreachable. "
            "Rate limiting may fall back to per-process memory and become inconsistent across replicas.",
            host,
            port,
        )
        if not settings.DEBUG:
            raise RuntimeError("RATE_LIMIT_STORAGE Redis backend is unreachable") from exc


async def _initialize_database(app: FastAPI) -> None:
    """Verify database connectivity, bootstrap secrets, hydrate settings, and init storage.

    Startup order:
    1. Cache service (in-memory, no DB needed)
    2. Database connectivity check
    3. Secret bootstrap (persist auto-generated secrets to DB)
    4. Runtime settings hydration from DB (DB is authoritative)
    5. Storage service init (S3 credentials may come from DB)
    6. Rate limit validation
    7. Startup checks
    """
    cache = CacheService()
    set_cache(cache)
    logger.info("[OK] Cache service initialized")

    await set_system_status("initializing", "Connecting services...")

    telemetry.update_service_status("database", healthy=True)
    logger.info("[OK] Database ready (migrations handled by start script)")

    # Bootstrap persistent secrets (first boot generates + persists to DB)
    try:
        from app.services.system.secret_bootstrap import ensure_persistent_secrets
        async with async_session_maker() as session:
            await ensure_persistent_secrets(session)
        logger.info("[OK] Persistent secrets bootstrapped")
    except Exception as exc:
        logger.error("[FAIL] Secret bootstrap failed: %s", exc)
        raise

    app.state.db_session_maker = async_session_maker

    await hydrate_runtime_settings_from_db(persist_normalized=True, commit=True)
    logger.info("[OK] Runtime settings hydrated from DB")

    # Storage init AFTER hydration (S3 credentials may come from DB)
    from app.services.storage import get_storage_service
    storage = get_storage_service()
    await storage.start()
    logger.info("[OK] Storage service initialized (mode: s3)")

    # Verify S3 connectivity
    try:
        storage_health = await storage.health_check()
    except Exception as e:
        storage_health = {"status": "unhealthy", "error": str(e)}
    if storage_health["status"] != "healthy":
        logger.error(
            "[FAIL] S3 storage is unreachable: %s. Configure S3_ENDPOINT_URL, S3_ACCESS_KEY, and S3_SECRET_KEY.",
            storage_health.get("error", "unknown"),
        )
    else:
        logger.info("[OK] S3 storage healthy (endpoint=%s)", storage_health.get("endpoint"))

    _validate_rate_limit_storage()

    await run_startup_checks()


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
            logger.info("[SKIP] sandbox_watchdog deferred to scheduler service")

            # Initialize warm pool manager
            from app.services.tools.sandbox import WarmPoolManager, set_warm_pool_manager

            warm_manager = WarmPoolManager(sandbox_pool)
            set_warm_pool_manager(warm_manager)

            async def warm_pool_maintain_loop():
                from sqlalchemy import text

                _warm_pool_lock_id = stable_lock_id("spectra_warm_pool")
                while True:
                    try:
                        await asyncio.sleep(30)
                        # Advisory lock prevents multiple API replicas from conflicting
                        async with async_session_maker() as session:
                            result = await session.execute(
                                text("SELECT pg_try_advisory_lock(:lock_id)"),
                                {"lock_id": _warm_pool_lock_id},
                            )
                            if not result.scalar():
                                continue
                        await warm_manager.maintain()
                    except asyncio.CancelledError:
                        break
                    except (OSError, RuntimeError) as e:
                        logger.error("Warm pool maintain error: %s", e)

            create_safe_task(warm_pool_maintain_loop(), name="warm_pool_maintain")
            create_safe_task(warm_manager.maintain(), name="warm_pool_initial")
            from app.services.tools.sandbox.warm_pool import WARM_POOL_SINGLE_NODE_FALLBACK

            logger.info(
                "[OK] Warm pool manager initialized (target = active sandbox_worker nodes, max 10, fallback=%d)",
                WARM_POOL_SINGLE_NODE_FALLBACK,
            )

            # Golden image rebuild on plugin changes — platform behaviour (not optional).
            from app.services.tools.sandbox import GoldenImageBuilder, set_image_builder

            builder = GoldenImageBuilder()
            set_image_builder(builder)

            async def on_plugin_change(**kwargs: Any) -> None:
                """Trigger golden image rebuild when plugins change."""
                create_safe_task(builder.build(), name="golden_image_build")

            events.subscribe(EventType.PLUGIN_UPDATED, on_plugin_change)
            logger.info("[OK] Golden image builder initialized (rebuild on PLUGIN_UPDATED)")
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
    if not settings.AI_SERVICE_URL:
        # In-process AI: preload embeddings
        try:
            from spectra_ai.embeddings import EmbeddingService

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

            create_safe_task(load_embeddings_with_status(), name="embedding_preload")
            logger.info("Triggered embedding model preloading")
        except (OSError, RuntimeError, ImportError) as e:
            logger.warning("Failed to trigger embedding preloading: %s", e)
    else:
        logger.info("[SKIP] Embedding preload deferred to ai-svc")

    # Initialize exploit database in background (loads from DB cache or downloads)
    if settings.EXPLOIT_DB_AUTO_INIT:
        try:
            from app.services.exploit_db import get_exploit_db

            async def _init_exploit_db() -> None:
                try:
                    db = get_exploit_db()
                    if not db._initialized:
                        await db.initialize()
                        logger.info("[OK] Exploit database initialized")
                except (OSError, RuntimeError) as e:
                    logger.warning("Exploit database initialization failed (data will load on demand): %s", e)

            create_safe_task(_init_exploit_db(), name="exploit_db_init")
            logger.info("Triggered exploit database initialization")
        except (ImportError, OSError) as e:
            logger.warning("Failed to trigger exploit database init: %s", e)

    await set_system_status("initializing", "Loading tool plugins...")

    # Initialize tool registry and load plugins
    try:
        from app.services.tools.registry import initialize_registry

        registry = await initialize_registry(
            plugins_dir="plugins",
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
    create_safe_task(run_startup_tasks(), name="startup_tasks")

    # Maintenance loops handled by scheduler service in multi-service mode
    if settings.SERVICE_MODE == "api":
        logger.info("[SKIP] Maintenance loops deferred to scheduler service")

    # Start metrics snapshot store
    from app.infrastructure.metrics_store import get_metrics_store

    metrics_store = get_metrics_store()
    await metrics_store.start()
    logger.info("[OK] Metrics store started")

    # Start OTLP export loop if configured
    otel_endpoint = getattr(settings, "OTEL_EXPORTER_ENDPOINT", "")
    if otel_endpoint and isinstance(otel_endpoint, str) and otel_endpoint.strip():
        create_safe_task(telemetry.start_export_loop(), name="otlp_export")
        logger.info("[OK] OTLP export loop started (endpoint=%s)", otel_endpoint)

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
        from app.mission.core.bridge import EventWebSocketBridge

        bridge = EventWebSocketBridge()
        bridge.start()
        logger.info("[OK] Event bridge started")
        return bridge
    except (OSError, RuntimeError, ImportError) as e:
        logger.warning("Failed to start event bridge: %s", e)
        return None


async def _config_change_listener() -> None:
    """Listen for config changes from other replicas and re-hydrate settings.

    Uses a raw asyncpg connection with LISTEN so that PostgreSQL pushes
    notifications instead of polling.
    """
    import asyncpg

    db_url = str(settings.DATABASE_URL)
    if isinstance(settings.DATABASE_URL, SecretStr):
        db_url = settings.DATABASE_URL.get_secret_value()
    # asyncpg needs a plain postgresql:// DSN, not the SQLAlchemy +asyncpg variant
    dsn = db_url.replace("postgresql+asyncpg://", "postgresql://")

    conn: asyncpg.Connection | None = None
    while True:
        try:
            if conn is None or conn.is_closed():
                conn = await asyncpg.connect(dsn)

                def _on_config_notify(
                    connection: asyncpg.Connection,
                    pid: int,
                    channel: str,
                    payload: str,
                ) -> None:
                    create_safe_task(_handle_config_change(), name="config_change_handler")

                await conn.add_listener("config_changes", _on_config_notify)
                logger.info("[OK] Config change listener connected (PG LISTEN)")

            # Keep the connection alive; reconnect on failure
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            if conn and not conn.is_closed():
                await conn.close()
            break
        except (OSError, asyncpg.PostgresError) as exc:
            logger.warning("Config change listener error (will retry): %s", exc)
            conn = None
            await asyncio.sleep(10)


async def _handle_config_change() -> None:
    """Re-hydrate settings from DB when another replica changes config."""
    try:
        async with async_session_maker() as session:
            await hydrate_runtime_settings_from_db(session)
        logger.info("Config re-hydrated from DB via LISTEN/NOTIFY")
    except (SQLAlchemyError, OSError) as exc:
        logger.warning("Failed to re-hydrate config on NOTIFY: %s", exc)


async def _blacklist_change_listener() -> None:
    """Listen for token blacklist changes from other replicas via PG LISTEN/NOTIFY."""
    import asyncpg

    db_url = str(settings.DATABASE_URL)
    if isinstance(settings.DATABASE_URL, SecretStr):
        db_url = settings.DATABASE_URL.get_secret_value()
    dsn = db_url.replace("postgresql+asyncpg://", "postgresql://")

    conn: asyncpg.Connection | None = None
    while True:
        try:
            if conn is None or conn.is_closed():
                conn = await asyncpg.connect(dsn)

                def _on_blacklist_notify(
                    connection: asyncpg.Connection,
                    pid: int,
                    channel: str,
                    payload: str,
                ) -> None:
                    create_safe_task(_handle_blacklist_change(), name="blacklist_change_handler")

                await conn.add_listener("token_blacklist_changed", _on_blacklist_notify)
                logger.info("[OK] Blacklist change listener connected (PG LISTEN)")

            await asyncio.sleep(5)
        except asyncio.CancelledError:
            if conn and not conn.is_closed():
                await conn.close()
            break
        except (OSError, asyncpg.PostgresError) as exc:
            logger.warning("Blacklist change listener error (will retry): %s", exc)
            conn = None
            await asyncio.sleep(10)


async def _handle_blacklist_change() -> None:
    """Reload blacklist from DB when another replica invalidates a token."""
    try:
        from app.auth.security import sync_blacklist_from_db

        await sync_blacklist_from_db()
        logger.info("Blacklist synced from DB via LISTEN/NOTIFY")
    except (SQLAlchemyError, OSError) as exc:
        logger.warning("Failed to sync blacklist on NOTIFY: %s", exc)


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
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=5.0)
            except TimeoutError:
                logger.warning("Timed out waiting for tasks to cancel")

        # Close service registry (all gateway connections)
        from app.services.gateway.service_registry import close_service_registry

        await close_service_registry()
        logger.info("[OK] Service registry closed")

        from app.services.gateway.ai_gateway import close_ai_gateway

        await close_ai_gateway()
        logger.info("[OK] AI gateway closed")

        from app.utils.geoip import close_geoip_session

        await close_geoip_session()
        logger.info("[OK] GeoIP session closed")

        from app.services.system.health import close_health_clients

        await close_health_clients()
        logger.info("[OK] Health clients closed")

        # Close smart router (TensorZero httpx client)
        from spectra_ai.router import close_smart_router

        await close_smart_router()
        logger.info("[OK] Smart router closed")

        # Close LLM client (no-op if never initialised — safe for all API modes).
        from spectra_ai.llm import close_global_llm_client

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

    if not settings.DATABASE_URL.get_secret_value():
        raise RuntimeError("DATABASE_URL must be explicitly set before starting Spectra")

    _validate_noop_payment()
    _validate_stripe_webhook_secret()

    if settings.PAYMENT_PROVIDER and not settings.PLATFORM_BASE_URL:
        logger.warning(
            "PLATFORM_BASE_URL is not set — payment callbacks and emails will use localhost fallback"
        )

    try:
        await _initialize_database(app)
        await _seed_default_data()
        await _initialize_services()
        logger.info("[READY] Spectra is ready!")
        _event_bridge = await _start_event_bridge()
        _config_listener_task = create_safe_task(_config_change_listener(), name="config_listener")
        _blacklist_listener_task = create_safe_task(
            _blacklist_change_listener(), name="blacklist_listener"
        )
    except (OSError, RuntimeError, ImportError) as e:
        logger.error("[ERROR] Startup failed: %s", e)
        raise

    yield

    # Cancel PG LISTEN tasks
    for _task in (_config_listener_task, _blacklist_listener_task):
        try:
            _task.cancel()
            await asyncio.wait_for(_task, timeout=3.0)
        except (asyncio.CancelledError, TimeoutError, NameError):
            pass

    if _event_bridge:
        try:
            _event_bridge.stop()
            logger.info("[OK] Event bridge stopped")
        except (OSError, RuntimeError) as e:
            logger.debug("Event bridge stop failed: %s", e)

    await _shutdown_services()
