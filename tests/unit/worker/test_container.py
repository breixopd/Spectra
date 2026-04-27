"""Tests for the DI container module."""

from unittest.mock import AsyncMock, patch

import pytest

# --- get_db_session ---


@pytest.mark.asyncio
async def test_get_db_session_yields_and_closes():
    from app.di.container import get_db_session

    mock_session = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.close = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.di.container.async_session_maker", return_value=ctx):
        gen = get_db_session()
        session = await gen.__anext__()
        assert session is mock_session

        # Exhaust the generator
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

    mock_session.close.assert_awaited_once()


# --- get_job_queue ---


def test_get_job_queue_returns_singleton():
    import app.di.container as container_mod

    container_mod.get_job_queue.cache_clear()

    with patch("app.infrastructure.queue.async_session_maker"):
        q1 = container_mod.get_job_queue()
        q2 = container_mod.get_job_queue()

    assert q1 is q2
    container_mod.get_job_queue.cache_clear()


# --- get_tool_registry ---


def test_get_tool_registry_returns_singleton():
    import app.di.container as container_mod

    container_mod.get_tool_registry.cache_clear()

    with patch("app.services.tools.registry.ToolRegistry.__init__", return_value=None):
        r1 = container_mod.get_tool_registry()
        r2 = container_mod.get_tool_registry()

    assert r1 is r2
    container_mod.get_tool_registry.cache_clear()


# --- get_gateway_client ---


def test_get_gateway_client_returns_client():
    from app.di.container import get_gateway_client

    with patch("app.services.gateway.http_client.GatewayClient.__init__", return_value=None):
        client = get_gateway_client("https://example.com", api_key="test-key")

    assert client is not None


# --- get_sandbox_pool ---


def test_get_sandbox_pool_returns_singleton():
    import app.di.container as container_mod

    container_mod.get_sandbox_pool.cache_clear()

    with patch("app.services.tools.sandbox.pool.SandboxPool.__init__", return_value=None):
        p1 = container_mod.get_sandbox_pool()
        p2 = container_mod.get_sandbox_pool()

    assert p1 is p2
    container_mod.get_sandbox_pool.cache_clear()


# --- get_storage_service ---


def test_get_storage_service_returns_new_instance():
    from app.di.container import get_storage_service

    with patch("app.services.storage.service.StorageService.__init__", return_value=None):
        s1 = get_storage_service()
        s2 = get_storage_service()

    # Not a singleton — each call returns a new instance
    assert s1 is not s2
