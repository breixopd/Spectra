"""
FastAPI Lifespan Manager.

Handles application startup and shutdown events.
Initializes database connections, Redis, and other services.
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator

from fastapi import FastAPI
from redis.asyncio import Redis

from app.core.cache import CacheService, set_cache
from app.core.config import settings
from app.core.constants import ARQ_QUEUE_NAME, REDIS_HEALTH_CHECK_INTERVAL
from app.core.database import async_session_maker, engine
from app.core.events import EventType, events
from app.core.telemetry import telemetry
from app.services.ai.llm import close_global_llm_client

logger = logging.getLogger("spectra.lifespan")


async def set_system_status(redis: Redis, status: str, message: str) -> None:
    """Update system status in Redis for UI polling."""
    try:
        await redis.hset(
            "spectra:system:status",
            mapping={
                "status": status,
                "message": message,
                "timestamp": datetime.now().isoformat(),
            },
        )
    except Exception as e:
        logger.debug("Failed to set system status: %s", e)


async def add_system_operation(
    redis: Redis, op_id: str, op_type: str, desc: str
) -> None:
    """Add an ongoing operation to the system status."""
    try:
        op = {
            "id": op_id,
            "type": op_type,
            "description": desc,
            "started_at": datetime.now().isoformat(),
        }
        await redis.hset("spectra:system:operations", op_id, json.dumps(op))
    except Exception as e:
        logger.debug("Failed to add system operation: %s", e)


async def remove_system_operation(redis: Redis, op_id: str) -> None:
    """Remove a completed operation."""
    try:
        await redis.hdel("spectra:system:operations", op_id)
    except Exception as e:
        logger.debug("Failed to remove system operation: %s", e)


async def run_startup_tasks(redis: Redis) -> None:
    """Run background tasks on startup."""
    try:
        logger.info("Running startup tasks...")

        # Queue tool installation via ARQ worker (tools container)
        await add_system_operation(
            redis, "tool_install", "install", "Installing security tools"
        )

        try:
            from arq import create_pool
            from arq.connections import RedisSettings

            # Queue install_all_tools job to the tools container
            redis_settings = RedisSettings(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                password=settings.REDIS_PASSWORD.get_secret_value(),
                database=settings.REDIS_DB,
            )

            pool = await create_pool(redis_settings, default_queue_name=ARQ_QUEUE_NAME)

            # Queue installation job
            job = await pool.enqueue_job("install_all_tools_job")
            logger.info(
                "Queued tool installation job: %s", job.job_id if job else "failed"
            )

            # Don't wait for completion - let it run in background
            # The UI will poll /api/system/status for progress

            await pool.close()

        except Exception as e:
            logger.warning("Failed to queue tool installation: %s", e)
        finally:
            await remove_system_operation(redis, "tool_install")

        await set_system_status(redis, "ready", "System ready")
        logger.info("Startup tasks completed")

    except Exception as e:
        logger.warning("Startup tasks failed: %s", e)
        await set_system_status(redis, "ready", "System ready (some tasks skipped)")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.

    Startup:
        - Connect to Redis
        - Initialize database tables
        - Load plugins and install tools
        - Load AI models (if local)
        - Run background setup tasks

    Shutdown:
        - Close Redis connection
        - Dispose database engine
        - Close LLM client
    """
    logger.info("[STARTUP] Starting Spectra...")

    # --- Startup ---
    try:
        # Redis connection
        app.state.redis = Redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            health_check_interval=REDIS_HEALTH_CHECK_INTERVAL,
        )
        await app.state.redis.ping()
        logger.info("[OK] Redis connected")

        # Set initial system status
        await set_system_status(
            app.state.redis, "initializing", "Connecting services..."
        )

        # Initialize cache service
        cache = CacheService(app.state.redis)
        set_cache(cache)
        logger.info("[OK] Cache service initialized")

        # Update telemetry with Redis health
        telemetry.update_service_status("redis", healthy=True)

        # Database migrations are handled by start.sh before uvicorn starts
        telemetry.update_service_status("database", healthy=True)
        logger.info("[OK] Database ready (migrations handled by start script)")

        # Store session maker in app state for dependency injection
        app.state.db_session_maker = async_session_maker

        await set_system_status(app.state.redis, "initializing", "Loading AI models...")

        # Preload embedding model in background (for RAG)
        try:
            from app.services.ai.embeddings import EmbeddingService

            await add_system_operation(
                app.state.redis, "embeddings", "load", "Loading embedding model"
            )
            embed_service = EmbeddingService()

            async def load_embeddings_with_status():
                try:
                    await embed_service._load_model()
                    logger.info("[OK] Embedding model loaded")
                except Exception as e:
                    logger.warning("Embedding model loading failed: %s", e)
                finally:
                    await remove_system_operation(app.state.redis, "embeddings")

            asyncio.create_task(load_embeddings_with_status())
            logger.info("Triggered embedding model preloading")
        except Exception as e:
            logger.warning("Failed to trigger embedding preloading: %s", e)

        await set_system_status(
            app.state.redis, "initializing", "Loading tool plugins..."
        )

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

        await set_system_status(app.state.redis, "initializing", "Installing tools...")

        # Trigger background setup tasks (including tool installation)
        asyncio.create_task(run_startup_tasks(app.state.redis))

        # Emit startup event
        await events.emit(
            EventType.SERVICE_HEALTH_CHANGED,
            source="lifespan",
            service="spectra",
            status="started",
        )

        logger.info("[READY] Spectra is ready!")

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
            except asyncio.TimeoutError:
                logger.warning("Timed out waiting for tasks to cancel")

        # Close LLM Client
        await close_global_llm_client()
        logger.info("[OK] LLM client closed")

        # Close Redis
        if hasattr(app.state, "redis"):
            await app.state.redis.close()
            logger.info("[OK] Redis disconnected")

        # Dispose database engine
        await engine.dispose()
        logger.info("[OK] Database connections closed")

    except Exception as e:
        logger.error("[ERROR] Shutdown error: %s", e)

    logger.info("[STOPPED] Spectra stopped.")
