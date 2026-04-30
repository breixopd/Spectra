"""Tests for app.bootstrap.lifespan module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI


class TestRunStartupChecks:
    @pytest.mark.asyncio
    @patch("app.bootstrap.lifespan.async_session_maker")
    async def test_startup_checks_succeed(self, mock_session_maker):
        from app.bootstrap.lifespan import run_startup_checks

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1
        mock_result.fetchall.return_value = [
            ("users",),
            ("missions",),
            ("targets",),
            ("findings",),
            ("exploits",),
        ]
        mock_session.execute.return_value = mock_result
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_maker.return_value = mock_session

        # Should complete without raising
        await run_startup_checks()

    @pytest.mark.asyncio
    @patch("app.bootstrap.lifespan.async_session_maker")
    async def test_startup_checks_handle_db_failure(self, mock_session_maker):
        from app.bootstrap.lifespan import run_startup_checks

        mock_session = AsyncMock()
        mock_session.execute.side_effect = OSError("connection refused")
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_maker.return_value = mock_session

        # Should NOT raise — checks are non-blocking
        await run_startup_checks()


class TestSetSystemStatus:
    @pytest.mark.asyncio
    @patch("app.bootstrap.lifespan.get_cache", create=True)
    async def test_set_system_status(self, mock_get_cache):
        from app.bootstrap.lifespan import set_system_status

        mock_cache = AsyncMock()
        mock_get_cache.return_value = mock_cache

        with patch("app.bootstrap.lifespan.get_cache", return_value=mock_cache):
            await set_system_status("ready", "All good")

    @pytest.mark.asyncio
    async def test_set_system_status_handles_error(self):
        from app.bootstrap.lifespan import set_system_status

        with patch("app.infrastructure.cache.get_cache", side_effect=RuntimeError("fail")):
            # Should not raise
            await set_system_status("error", "bad")


class TestAddRemoveSystemOperation:
    @pytest.mark.asyncio
    async def test_add_system_operation(self):
        from app.bootstrap.lifespan import add_system_operation

        mock_cache = AsyncMock()
        with patch("app.infrastructure.cache.get_cache", return_value=mock_cache):
            await add_system_operation("op1", "install", "Installing tools")
            mock_cache.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_system_operation(self):
        from app.bootstrap.lifespan import remove_system_operation

        mock_cache = AsyncMock()
        with patch("app.infrastructure.cache.get_cache", return_value=mock_cache):
            await remove_system_operation("op1")
            mock_cache.delete.assert_called_once()


def _make_done_task(coro):
    """Create a real asyncio.Task from *coro* so shutdown can cancel/await it."""
    if asyncio.iscoroutine(coro):
        coro.close()
    fut = asyncio.get_event_loop().create_future()
    fut.set_result(None)
    return fut


class TestLifespanContextManager:
    @pytest.mark.asyncio
    @patch("app.bootstrap.lifespan.engine")
    @patch("spectra_ai.llm.close_global_llm_client", new_callable=AsyncMock)
    @patch("app.bootstrap.lifespan.async_session_maker")
    @patch("app.bootstrap.lifespan.CacheService")
    @patch("app.bootstrap.lifespan.set_cache")
    @patch("app.bootstrap.lifespan.events")
    @patch("app.bootstrap.lifespan.telemetry")
    @patch("app.bootstrap.lifespan.settings")
    @patch("app.bootstrap.lifespan.hydrate_runtime_settings_from_db", new_callable=AsyncMock)
    @patch("app.bootstrap.lifespan.run_startup_checks", new_callable=AsyncMock)
    @patch("app.bootstrap.lifespan.seed_default_plans", new_callable=AsyncMock)
    @patch("app.bootstrap.lifespan.set_system_status", new_callable=AsyncMock)
    @patch("app.bootstrap.lifespan.run_startup_tasks", new_callable=AsyncMock)
    @patch("app.bootstrap.lifespan.add_system_operation", new_callable=AsyncMock)
    @patch("app.bootstrap.lifespan.remove_system_operation", new_callable=AsyncMock)
    @patch("app.services.system.secret_bootstrap.ensure_persistent_secrets", new_callable=AsyncMock)
    async def test_lifespan_startup_and_shutdown(
        self,
        mock_ensure_secrets,
        mock_remove_op,
        mock_add_op,
        mock_startup_tasks,
        mock_set_status,
        mock_seed_plans,
        mock_startup_checks,
        mock_hydrate,
        mock_settings,
        mock_telemetry,
        mock_events,
        mock_set_cache,
        mock_cache_service,
        mock_session_maker,
        mock_close_llm,
        mock_engine,
    ):
        from app.bootstrap.lifespan import lifespan

        mock_settings.DEBUG = True  # Skip production security checks
        mock_settings.SERVICE_MODE = "api"
        mock_events.emit = AsyncMock()
        mock_engine.dispose = AsyncMock()

        # Mock all lazy imports used during startup
        mock_storage = MagicMock()
        mock_storage.is_s3 = True
        mock_storage.start = AsyncMock()
        mock_storage.health_check = AsyncMock(return_value={"status": "healthy", "endpoint": "http://garage:3900"})

        with (
            patch("app.services.storage.get_storage_service", return_value=mock_storage),
            patch("app.services.storage.close_storage_service", new_callable=AsyncMock),
            patch(
                "app.services.tools.registry.initialize_registry",
                new_callable=AsyncMock,
                return_value=MagicMock(list_tools=MagicMock(return_value=[])),
            ),
            patch("app.services.tools.sandbox.SandboxPool", return_value=MagicMock(available=False)),
            patch("app.services.tools.sandbox.set_sandbox_pool"),
            patch("app.services.gateway.service_registry.get_service_registry", return_value=MagicMock()),
            patch("app.services.gateway.service_registry.close_service_registry", new_callable=AsyncMock),
            patch("spectra_ai.embeddings.EmbeddingService", return_value=MagicMock(_load_model=AsyncMock())),
            patch("app.infrastructure.metrics_store.get_metrics_store", return_value=MagicMock(start=AsyncMock())),
            patch("app.bootstrap.lifespan._validate_rate_limit_storage"),
            patch(
                "app.services.scaling.get_pool_manager",
                return_value=MagicMock(start_health_loop=AsyncMock(), stop_health_loop=AsyncMock()),
            ),
            patch("app.bootstrap.lifespan._config_change_listener", new_callable=AsyncMock),
            patch("app.bootstrap.lifespan._blacklist_change_listener", new_callable=AsyncMock),
            patch(
                "app.bootstrap.lifespan.create_safe_task",
                side_effect=lambda coro, **kw: _make_done_task(coro),
            ),
            patch("app.mission.core.bridge.EventWebSocketBridge", return_value=MagicMock()),
        ):
            app = FastAPI()
            app.state = MagicMock()

            async with lifespan(app):
                # During lifespan: startup checks should have been called
                mock_startup_checks.assert_called_once()
                mock_hydrate.assert_called_once()
                mock_seed_plans.assert_called_once()

            # After lifespan exits: shutdown should have happened
            mock_close_llm.assert_called_once()
            mock_engine.dispose.assert_called_once()
