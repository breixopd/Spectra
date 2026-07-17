"""Tests for spectra_api.bootstrap.lifespan module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI


class TestRunStartupChecks:
    @pytest.mark.asyncio
    @patch("spectra_api.bootstrap.lifespan.async_session_maker")
    async def test_startup_checks_succeed(self, mock_session_maker):
        from spectra_api.bootstrap.lifespan import run_startup_checks

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
    @patch("spectra_api.bootstrap.lifespan.async_session_maker")
    async def test_startup_checks_handle_db_failure(self, mock_session_maker):
        from spectra_api.bootstrap.lifespan import run_startup_checks

        mock_session = AsyncMock()
        mock_session.execute.side_effect = OSError("connection refused")
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_maker.return_value = mock_session

        # Should NOT raise — checks are non-blocking
        await run_startup_checks()


class TestSetSystemStatus:
    @pytest.mark.asyncio
    @patch("spectra_api.bootstrap.lifespan.get_cache", create=True)
    async def test_set_system_status(self, mock_get_cache):
        from spectra_api.bootstrap.lifespan import set_system_status

        mock_cache = AsyncMock()
        mock_get_cache.return_value = mock_cache

        with patch("spectra_api.bootstrap.lifespan.get_cache", return_value=mock_cache):
            await set_system_status("ready", "All good")

    @pytest.mark.asyncio
    async def test_set_system_status_handles_error(self):
        from spectra_api.bootstrap.lifespan import set_system_status

        with patch("spectra_infra.cache.get_cache", side_effect=RuntimeError("fail")):
            # Should not raise
            await set_system_status("error", "bad")


class TestSandboxControllerInitialization:
    @pytest.mark.asyncio
    async def test_remote_controller_never_performs_app_lifecycle_cleanup(self):
        from pydantic import SecretStr

        from spectra_api.bootstrap import lifespan as lifespan_mod

        controller = MagicMock(available=True, is_remote=True)
        fake_settings = MagicMock(
            SANDBOX_ORCHESTRATOR_URL="http://scheduler:5011",
            SANDBOX_ORCHESTRATOR_TIMEOUT=30,
            SANDBOX_ORCHESTRATOR_API_KEY=SecretStr("api-key"),
            SERVICE_AUTH_SECRET=SecretStr("service-secret"),
        )
        with (
            patch.object(lifespan_mod, "settings", fake_settings),
            patch(
                "spectra_ai_core.gateway.sandbox_orchestrator.SandboxOrchestratorClient", return_value=controller
            ) as client_cls,
            patch("spectra_tools.sandbox.set_sandbox_pool") as set_pool,
            patch("spectra_tools.sandbox.SandboxPool") as local_pool_cls,
        ):
            await lifespan_mod._initialize_sandbox()

        client_cls.assert_called_once_with(
            "http://scheduler:5011",
            timeout=30,
            api_key="api-key",
            service_auth="service-secret",
        )
        set_pool.assert_called_once_with(controller)
        local_pool_cls.assert_not_called()
        controller.cleanup_all.assert_not_called()


class TestAddRemoveSystemOperation:
    @pytest.mark.asyncio
    async def test_add_system_operation(self):
        from spectra_api.bootstrap.lifespan import add_system_operation

        mock_cache = AsyncMock()
        with patch("spectra_infra.cache.get_cache", return_value=mock_cache):
            await add_system_operation("op1", "install", "Installing tools")
            mock_cache.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_system_operation(self):
        from spectra_api.bootstrap.lifespan import remove_system_operation

        mock_cache = AsyncMock()
        with patch("spectra_infra.cache.get_cache", return_value=mock_cache):
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
    @patch("spectra_api.bootstrap.lifespan.engine")
    @patch("spectra_ai_core.llm.close_global_llm_client", new_callable=AsyncMock)
    @patch("spectra_api.bootstrap.lifespan.async_session_maker")
    @patch("spectra_api.bootstrap.lifespan.CacheService")
    @patch("spectra_api.bootstrap.lifespan.set_cache")
    @patch("spectra_api.bootstrap.lifespan.events")
    @patch("spectra_api.bootstrap.lifespan.telemetry")
    @patch("spectra_api.bootstrap.lifespan.settings")
    @patch("spectra_api.bootstrap.lifespan.hydrate_runtime_settings_from_db", new_callable=AsyncMock)
    @patch("spectra_api.bootstrap.lifespan.run_startup_checks", new_callable=AsyncMock)
    @patch("spectra_api.bootstrap.lifespan.seed_default_plans", new_callable=AsyncMock)
    @patch("spectra_api.bootstrap.lifespan.set_system_status", new_callable=AsyncMock)
    @patch("spectra_api.bootstrap.lifespan.run_startup_tasks", new_callable=AsyncMock)
    @patch("spectra_api.bootstrap.lifespan.add_system_operation", new_callable=AsyncMock)
    @patch("spectra_api.bootstrap.lifespan.remove_system_operation", new_callable=AsyncMock)
    @patch("spectra_system.secret_bootstrap.ensure_persistent_secrets", new_callable=AsyncMock)
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
        from spectra_api.bootstrap.lifespan import lifespan

        mock_settings.DEBUG = True  # Skip production security checks
        mock_settings.SERVICE_MODE = "api"
        mock_settings.SANDBOX_ORCHESTRATOR_URL = None
        mock_events.emit = AsyncMock()
        mock_engine.dispose = AsyncMock()

        # Mock all lazy imports used during startup
        mock_storage = MagicMock()
        mock_storage.is_s3 = True
        mock_storage.start = AsyncMock()
        mock_storage.health_check = AsyncMock(return_value={"status": "healthy", "endpoint": "http://garage:3900"})

        with (
            patch("spectra_storage_policy.storage.get_storage_service", return_value=mock_storage),
            patch("spectra_storage_policy.storage.close_storage_service", new_callable=AsyncMock),
            patch(
                "spectra_tools_core.registry.initialize_registry",
                new_callable=AsyncMock,
                return_value=MagicMock(list_tools=MagicMock(return_value=[])),
            ),
            patch("spectra_tools.sandbox.SandboxPool", return_value=MagicMock(available=False)),
            patch("spectra_tools.sandbox.set_sandbox_pool"),
            patch("spectra_ai_core.gateway.service_registry.get_service_registry", return_value=MagicMock()),
            patch("spectra_ai_core.gateway.service_registry.close_service_registry", new_callable=AsyncMock),
            patch("spectra_ai_core.embeddings.EmbeddingService", return_value=MagicMock(_load_model=AsyncMock())),
            patch("spectra_infra.metrics_store.get_metrics_store", return_value=MagicMock(start=AsyncMock())),
            patch("spectra_api.bootstrap.lifespan._validate_rate_limit_storage"),
            patch(
                "spectra_scaling.get_pool_manager",
                return_value=MagicMock(start_health_loop=AsyncMock(), stop_health_loop=AsyncMock()),
            ),
            patch("spectra_api.bootstrap.lifespan._config_change_listener", new_callable=AsyncMock),
            patch("spectra_api.bootstrap.lifespan._blacklist_change_listener", new_callable=AsyncMock),
            patch(
                "spectra_api.bootstrap.lifespan.create_safe_task",
                side_effect=lambda coro, **kw: _make_done_task(coro),
            ),
            patch("spectra_mission.core.bridge.EventWebSocketBridge", return_value=MagicMock()),
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
