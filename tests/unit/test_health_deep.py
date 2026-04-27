"""Deep tests for canonical health collection and route wrappers."""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.routers.health import health_check, readiness_check, service_health
from app.services.system.health import _health_cache, _is_control_plane_health_url, collect_platform_health, probe_http_health


@pytest.fixture(autouse=True)
def _clear_health_cache():
    _health_cache.clear()


def _mock_response():
    resp = MagicMock()
    resp.status_code = 200
    return resp


def _mock_request(*, service_auth: str | None = None):
    req = MagicMock()
    req.headers = {"X-Service-Auth": service_auth} if service_auth else {}
    req.cookies = {}
    req.query_params = {}
    return req


@contextmanager
def _mock_core_checks(redis_ok=True, s3_ok=True):
    mock_redis_conn = AsyncMock()
    mock_redis_conn.ping = AsyncMock()
    mock_redis_conn.aclose = AsyncMock()
    from_url_mock = MagicMock(return_value=mock_redis_conn) if redis_ok else MagicMock(side_effect=ConnectionError)

    mock_storage = MagicMock()
    mock_storage.health_check = AsyncMock(
        return_value={"status": "healthy"} if s3_ok else {"status": "unhealthy", "error": "unreachable"}
    )

    with (
        patch.dict("sys.modules", {"app.services.storage": MagicMock(get_storage_service=lambda: mock_storage)}),
        patch("redis.asyncio.from_url", from_url_mock),
    ):
        yield


def _settings(**overrides):
    values = {
        "RATE_LIMIT_STORAGE": "redis://redis:6379",
        "AI_SERVICE_URL": "http://ai-svc:5010",
        "TENSORZERO_GATEWAY_URL": "http://tensorzero:3000",
        "SCHEDULER_SERVICE_URL": "http://scheduler:5011",
        "WORKER_SERVICE_URL": "http://worker:5012",
        "SERVICE_AUTH_SECRET": MagicMock(get_secret_value=lambda: "svc-secret"),
    }
    values.update(overrides)
    return MagicMock(**values)


def test_control_plane_health_url_blocks_target_probe_urls():
    assert _is_control_plane_health_url("http://worker:5012", "worker", {}) is True
    assert _is_control_plane_health_url("http://example.com", "worker", {}) is False
    assert _is_control_plane_health_url("http://worker:5012", "target", {}) is False
    assert _is_control_plane_health_url("http://worker:5012", "worker", {"target_probe": True}) is False


@pytest.mark.asyncio
async def test_collect_platform_health_basic_includes_core_and_services():
    db = AsyncMock()
    db.execute = AsyncMock()
    probes = [
        {"status": "healthy", "latency_ms": 1.0, "critical": True, "path": "/health"},
        {"status": "healthy", "latency_ms": 2.0, "critical": True, "path": "/health"},
        {"status": "healthy", "latency_ms": 3.0, "critical": True, "path": "/health"},
        {"status": "healthy", "latency_ms": 4.0, "critical": True, "path": "/health"},
    ]

    with (
        _mock_core_checks(),
        patch("app.services.system.health.get_settings", return_value=_settings()),
        patch("app.services.system.health.probe_http_health", new=AsyncMock(side_effect=probes)) as probe,
    ):
        result = await collect_platform_health(db, detail="basic", scope="platform")

    assert result["status"] == "healthy"
    assert result["service"] == "spectra"
    assert "version" in result
    assert result["components"]["database"]["status"] == "healthy"
    assert "latency_ms" in result["components"]["database"]
    assert result["services"]["ai_service"]["status"] == "healthy"
    assert probe.await_args_list[0].kwargs["path"] == "/health"


@pytest.mark.asyncio
async def test_health_basic_marks_degraded_when_core_dependency_fails():
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=ConnectionError("refused"))
    response = _mock_response()

    with (
        _mock_core_checks(),
        patch("app.services.system.health.get_settings", return_value=_settings(AI_SERVICE_URL="")),
        patch("app.services.system.health.probe_http_health", new=AsyncMock(return_value={"status": "not_configured", "critical": False})),
    ):
        result = await health_check(request=_mock_request(), response=response, db=db)

    assert result["status"] == "degraded"
    assert result["components"]["database"]["status"] == "unhealthy"
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_full_health_requires_admin_or_service_auth():
    db = AsyncMock()
    db.execute = AsyncMock()
    response = _mock_response()

    with patch("app.api.routers.health._get_settings", return_value=_settings()):
        with pytest.raises(Exception) as exc:
            await health_check(request=_mock_request(), response=response, db=db, detail="full")

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_full_health_allows_service_auth_and_includes_latency():
    db = AsyncMock()
    db.execute = AsyncMock()
    response = _mock_response()
    mock_gw = AsyncMock()
    mock_gw.check_llm_status.return_value = {"available": True, "provider": "openai", "status": "configured: openai"}
    mock_gw.check_embeddings_status.return_value = {"functional": True, "status": "healthy"}

    with (
        _mock_core_checks(),
        patch("app.api.routers.health._get_settings", return_value=_settings()),
        patch("app.services.system.health.get_settings", return_value=_settings()),
        patch("app.services.gateway.ai_gateway.get_ai_gateway", return_value=mock_gw),
        patch("app.infrastructure.cache.get_cache", return_value=None),
        patch("app.services.tools.sandbox.get_sandbox_pool", return_value=None),
        patch("app.services.system.health.probe_http_health", new=AsyncMock(return_value={"status": "healthy", "critical": True, "latency_ms": 1.2})),
        patch("app.services.system.health._collect_nodes", new=AsyncMock(return_value={})),
    ):
        result = await health_check(
            request=_mock_request(service_auth="svc-secret"),
            response=response,
            db=db,
            detail="full",
        )

    assert "llm" in result["components"]
    assert result["components"]["llm"]["provider"] == "openai"
    assert "latency_ms" in result["components"]["llm"]
    assert "nodes" in result


@pytest.mark.asyncio
async def test_readiness_uses_canonical_health_checks():
    db = AsyncMock()
    db.execute = AsyncMock()
    response = _mock_response()
    mock_gw = AsyncMock()
    mock_gw.check_llm_status.return_value = {"available": True, "provider": "openai", "status": "configured: openai"}
    mock_gw.check_embeddings_status.return_value = {"functional": True, "status": "healthy"}

    with (
        _mock_core_checks(),
        patch("app.services.system.health.get_settings", return_value=_settings()),
        patch("app.services.gateway.ai_gateway.get_ai_gateway", return_value=mock_gw),
        patch("app.infrastructure.cache.get_cache", return_value=None),
        patch("app.services.tools.sandbox.get_sandbox_pool", return_value=None),
        patch("app.services.system.health.probe_http_health", new=AsyncMock(return_value={"status": "healthy", "critical": True, "latency_ms": 1.0})),
    ):
        result = await readiness_check(response=response, db=db)

    assert result["ready"] is False
    assert result["checks"]["database"] is True
    assert result["checks"]["llm"] is True
    assert result["checks"]["cache"] is False
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_service_health_requires_admin():
    db = AsyncMock()
    with patch("app.api.routers.health._get_settings", return_value=_settings()):
        with pytest.raises(Exception) as exc:
            await service_health(request=_mock_request(), db=db)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_service_health_returns_nodes_for_internal_call():
    db = AsyncMock()
    response = {
        "status": "healthy",
        "services": {"worker": {"status": "healthy", "latency_ms": 5.0}},
        "nodes": {"worker": [{"name": "node-1", "status": "healthy", "latency_ms": 5.5}]},
        "instance": "test",
        "timestamp": "now",
        "summary": {"nodes": {"total": 1, "healthy": 1}},
    }

    with (
        patch("app.api.routers.health._get_settings", return_value=_settings()),
        patch("app.api.routers.health.collect_platform_health", new=AsyncMock(return_value=response)),
    ):
        result = await service_health(request=_mock_request(service_auth="svc-secret"), db=db)

    assert result["services"]["worker"]["latency_ms"] == 5.0
    assert result["nodes"]["worker"][0]["latency_ms"] == 5.5


def test_probe_http_health_wrapper():
    with patch("app.api.routers.health.probe_http_health", new=AsyncMock(return_value={"status": "healthy"})) as mock_probe:
        from app.api.routers.health import _probe_http_health

        result = asyncio.run(_probe_http_health("http://test", path="/health"))
    assert result is True
    mock_probe.assert_awaited_once_with("http://test", path="/health")


def test_probe_http_health_wrapper_unhealthy():
    with patch("app.api.routers.health.probe_http_health", new=AsyncMock(return_value={"status": "degraded"})):
        from app.api.routers.health import _probe_http_health

        result = asyncio.run(_probe_http_health("http://test", path="/health"))
    assert result is False


import asyncio


def test_data_dir():
    from app.api.routers.health import _data_dir

    assert _data_dir() == "/app/data"


@pytest.mark.asyncio
async def test_get_version():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.api.routers.health import router as health_router

    app = FastAPI()
    app.include_router(health_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/version")
    assert resp.status_code == 200
    assert "version" in resp.json()


@pytest.mark.asyncio
async def test_service_health_degraded_logs_debug():
    db = AsyncMock()
    response = {
        "status": "degraded",
        "services": {},
        "nodes": {},
        "instance": "test",
        "timestamp": "now",
        "summary": {"nodes": {"total": 0, "healthy": 0}},
    }

    with (
        patch("app.api.routers.health._get_settings", return_value=_settings()),
        patch("app.api.routers.health.collect_platform_health", new=AsyncMock(return_value=response)),
        patch("app.api.routers.health.logger") as mock_logger,
    ):
        result = await service_health(request=_mock_request(service_auth="svc-secret"), db=db)

    assert result["status"] == "degraded"
    mock_logger.debug.assert_called_once()


@pytest.mark.asyncio
async def test_probe_http_health_reports_latency_and_status():
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {"status": "healthy"}
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_client

    with patch("httpx.AsyncClient", return_value=mock_context):
        result = await probe_http_health("http://worker:5012", path="/health")

    assert result["status"] == "healthy"
    assert result["path"] == "/health"
    assert "latency_ms" in result
