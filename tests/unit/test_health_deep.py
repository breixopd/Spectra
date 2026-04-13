"""Deep tests for the health check router (/api/health)."""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.api.routers.health import health_check, readiness_check


def _mock_response():
    resp = MagicMock()
    resp.status_code = 200
    return resp


def _mock_request():
    req = MagicMock()
    req.headers = {}
    req.cookies = {}
    req.query_params = {}
    return req


@contextmanager
def _mock_infra_checks(redis_ok=True, s3_ok=True, extra_modules=None):
    """Patch Redis and S3 checks that run in non-verbose mode."""
    mock_redis_conn = AsyncMock()
    mock_redis_conn.ping = AsyncMock()
    mock_redis_conn.aclose = AsyncMock()

    mock_storage = MagicMock()
    s3_status = {"status": "healthy"} if s3_ok else {"status": "unhealthy", "error": "unreachable"}
    mock_storage.health_check = AsyncMock(return_value=s3_status)

    if redis_ok:
        from_url_mock = MagicMock(return_value=mock_redis_conn)
    else:
        from_url_mock = MagicMock(side_effect=ConnectionError("refused"))

    modules = {}
    if extra_modules:
        modules.update(extra_modules)
    modules["app.services.storage"] = MagicMock(get_storage_service=MagicMock(return_value=mock_storage))

    with patch.dict("sys.modules", modules), patch("redis.asyncio.from_url", from_url_mock):
        yield


# ---------------------------------------------------------------------------
# GET /health — basic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_returns_healthy_when_db_ok():
    db = AsyncMock()
    db.execute = AsyncMock()
    response = _mock_response()

    with _mock_infra_checks():
        result = await health_check(request=_mock_request(), response=response, db=db, verbose=False)

    assert result["status"] == "healthy"
    assert result["service"] == "spectra"
    assert "version" in result
    assert result["components"]["database"]["status"] == "healthy"
    assert "latency_ms" in result["components"]["database"]


@pytest.mark.asyncio
async def test_health_returns_degraded_when_db_fails():
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=ConnectionError("refused"))
    response = _mock_response()

    with _mock_infra_checks():
        result = await health_check(request=_mock_request(), response=response, db=db, verbose=False)

    assert result["status"] == "degraded"
    assert result["components"]["database"]["status"] == "unhealthy"
    assert result["components"]["database"]["error"] == "ConnectionError"
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_health_non_verbose_excludes_extras():
    db = AsyncMock()
    db.execute = AsyncMock()
    response = _mock_response()

    with _mock_infra_checks():
        result = await health_check(request=_mock_request(), response=response, db=db, verbose=False)

    assert "embeddings" not in result["components"]
    assert "llm" not in result["components"]
    assert "cache" not in result["components"]
    assert "disk" not in result["components"]
    # Redis and S3 are now in basic mode
    assert "redis" in result["components"]
    assert "s3" in result["components"]


# ---------------------------------------------------------------------------
# GET /health?verbose=true — component details
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_verbose_includes_embeddings():
    db = AsyncMock()
    db.execute = AsyncMock()
    response = _mock_response()

    mock_gw = AsyncMock()
    mock_gw.check_embeddings_status.return_value = {"functional": True, "status": "healthy"}

    with _mock_infra_checks():
        with (
            patch("app.api.routers.health._extract_request_token", return_value=("tok", "header")),
            patch("app.api.routers.health._decode_access_payload", return_value={"sub": "u-1"}),
            patch(
                "app.api.routers.health._load_active_user_from_payload_with_session",
                new_callable=AsyncMock,
                return_value=MagicMock(),
            ),
            patch("app.services.gateway.ai_gateway.get_ai_gateway", return_value=mock_gw),
        ):
            result = await health_check(request=_mock_request(), response=response, db=db, verbose=True)

    assert "embeddings" in result["components"]


@pytest.mark.asyncio
async def test_health_verbose_includes_llm():
    db = AsyncMock()
    db.execute = AsyncMock()
    response = _mock_response()

    mock_gw = AsyncMock()
    mock_gw.check_embeddings_status.return_value = {"functional": False, "status": "fallback"}
    mock_gw.check_llm_status.return_value = {"available": True, "provider": "openai", "status": "configured: openai"}

    mock_cache = MagicMock()
    mock_cache.get_stats.return_value = {"hit_rate_percent": 85}

    mock_pool = MagicMock()
    mock_pool.available = True

    with (
        _mock_infra_checks(
        extra_modules={
            "app.core.cache": MagicMock(get_cache=lambda: mock_cache),
            "app.services.tools.sandbox": MagicMock(get_sandbox_pool=lambda: mock_pool),
        }
    ), patch("app.api.routers.health._extract_request_token", return_value=("tok", "header")),
        patch("app.api.routers.health._decode_access_payload", return_value={"sub": "u-1"}),
        patch(
            "app.api.routers.health._load_active_user_from_payload_with_session",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ),
        patch("app.services.gateway.ai_gateway.get_ai_gateway", return_value=mock_gw),
    ):
        result = await health_check(request=_mock_request(), response=response, db=db, verbose=True)

    assert "llm" in result["components"]
    assert "openai" in result["components"]["llm"]


@pytest.mark.asyncio
async def test_health_verbose_cache_healthy():
    db = AsyncMock()
    db.execute = AsyncMock()
    response = _mock_response()

    mock_cache = MagicMock()
    mock_cache.get_stats.return_value = {"hit_rate_percent": 42}

    mock_gw = AsyncMock()
    mock_gw.check_embeddings_status.return_value = {"functional": False, "status": "fallback"}
    mock_gw.check_llm_status.return_value = {"available": False, "provider": "unknown", "status": "unavailable"}

    with (
        _mock_infra_checks(
        extra_modules={
            "app.core.cache": MagicMock(get_cache=lambda: mock_cache),
            "app.services.tools.sandbox": MagicMock(get_sandbox_pool=lambda: None),
        }
    ), patch("app.api.routers.health._extract_request_token", return_value=("tok", "header")),
        patch("app.api.routers.health._decode_access_payload", return_value={"sub": "u-1"}),
        patch(
            "app.api.routers.health._load_active_user_from_payload_with_session",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ),
        patch("app.services.gateway.ai_gateway.get_ai_gateway", return_value=mock_gw),
    ):
        result = await health_check(request=_mock_request(), response=response, db=db, verbose=True)

    assert result["components"]["cache"]["status"] == "healthy"
    assert result["components"]["cache"]["hit_rate_percent"] == 42


@pytest.mark.asyncio
async def test_health_verbose_cache_unavailable():
    db = AsyncMock()
    db.execute = AsyncMock()
    response = _mock_response()

    mock_gw = AsyncMock()
    mock_gw.check_embeddings_status.return_value = {"functional": False, "status": "fallback"}
    mock_gw.check_llm_status.return_value = {"available": False, "provider": "unknown", "status": "unavailable"}

    with (
        _mock_infra_checks(
        extra_modules={
            "app.core.cache": MagicMock(get_cache=lambda: None),
            "app.services.tools.sandbox": MagicMock(get_sandbox_pool=MagicMock(side_effect=RuntimeError)),
        }
    ), patch("app.api.routers.health._extract_request_token", return_value=("tok", "header")),
        patch("app.api.routers.health._decode_access_payload", return_value={"sub": "u-1"}),
        patch(
            "app.api.routers.health._load_active_user_from_payload_with_session",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ),
        patch("app.services.gateway.ai_gateway.get_ai_gateway", return_value=mock_gw),
    ):
        result = await health_check(request=_mock_request(), response=response, db=db, verbose=True)

    assert result["components"]["cache"]["status"] == "unavailable"


@pytest.mark.asyncio
async def test_health_verbose_disk_info():
    db = AsyncMock()
    db.execute = AsyncMock()
    response = _mock_response()

    mock_usage = MagicMock()
    mock_usage.free = 50 * (1024**3)
    mock_usage.total = 100 * (1024**3)
    mock_usage.used = 50 * (1024**3)

    mock_gw = AsyncMock()
    mock_gw.check_embeddings_status.return_value = {"functional": False, "status": "fallback"}
    mock_gw.check_llm_status.return_value = {"available": False, "provider": "unknown", "status": "unavailable"}

    with _mock_infra_checks(
        extra_modules={
            "app.core.cache": MagicMock(get_cache=lambda: None),
            "app.services.tools.sandbox": MagicMock(get_sandbox_pool=MagicMock(side_effect=RuntimeError)),
        }
    ), patch("app.api.routers.health.shutil.disk_usage", return_value=mock_usage), patch("app.services.gateway.ai_gateway.get_ai_gateway", return_value=mock_gw):
        with (
            patch("app.api.routers.health._extract_request_token", return_value=("tok", "header")),
            patch("app.api.routers.health._decode_access_payload", return_value={"sub": "u-1"}),
            patch(
                "app.api.routers.health._load_active_user_from_payload_with_session",
                new_callable=AsyncMock,
                return_value=MagicMock(),
            ),
        ):
            result = await health_check(request=_mock_request(), response=response, db=db, verbose=True)

    assert result["components"]["disk"]["status"] == "healthy"
    assert result["components"]["disk"]["used_percent"] == 50.0


# ---------------------------------------------------------------------------
# GET /health/ready — readiness probe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_readiness_all_ready():
    db = AsyncMock()
    db.execute = AsyncMock()
    response = _mock_response()

    mock_gw = AsyncMock()
    mock_gw.check_llm_status.return_value = {"available": True, "provider": "openai", "status": "configured: openai"}
    mock_gw.check_embeddings_status.return_value = {"functional": True, "status": "healthy"}

    probe_health = AsyncMock(return_value=True)

    with (
        patch("app.services.gateway.ai_gateway.get_ai_gateway", return_value=mock_gw),
        patch("app.api.routers.health._get_settings", return_value=MagicMock(
            AI_SERVICE_URL="http://ai-svc:5010",
            TENSORZERO_GATEWAY_URL="http://tensorzero:3000",
            SCHEDULER_SERVICE_URL="http://scheduler:5011",
            WORKER_SERVICE_URL="http://worker:5012",
        )),
        patch("app.api.routers.health._probe_http_health", new=probe_health),
    ):
        result = await readiness_check(response=response, db=db)

    assert result["ready"] is True
    assert result["checks"]["database"] is True
    assert result["checks"]["ai_service"] is True
    assert result["checks"]["tensorzero"] is True
    assert result["checks"]["scheduler"] is True
    assert result["checks"]["worker"] is True
    probe_health.assert_has_awaits(
        [
            call("http://ai-svc:5010", path="/health"),
            call("http://tensorzero:3000", path="/health"),
            call("http://scheduler:5011", path="/health"),
            call("http://worker:5012", path="/health"),
        ]
    )


@pytest.mark.asyncio
async def test_readiness_db_down():
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=OSError("db down"))
    response = _mock_response()

    mock_gw = AsyncMock()
    mock_gw.check_llm_status.return_value = {"available": True, "provider": "openai", "status": "configured: openai"}
    mock_gw.check_embeddings_status.return_value = {"functional": True, "status": "healthy"}

    with (
        patch("app.services.gateway.ai_gateway.get_ai_gateway", return_value=mock_gw),
        patch("app.api.routers.health._get_settings", return_value=MagicMock(
            AI_SERVICE_URL="http://ai-svc:5010",
            TENSORZERO_GATEWAY_URL="http://tensorzero:3000",
            SCHEDULER_SERVICE_URL="http://scheduler:5011",
            WORKER_SERVICE_URL="http://worker:5012",
        )),
        patch("app.api.routers.health._probe_http_health", new=AsyncMock(return_value=True)),
    ):
        result = await readiness_check(response=response, db=db)

    assert result["ready"] is False
    assert result["checks"]["database"] is False
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_readiness_llm_unavailable():
    db = AsyncMock()
    db.execute = AsyncMock()
    response = _mock_response()

    mock_gw = AsyncMock()
    mock_gw.check_llm_status.return_value = {"available": False, "provider": "unknown", "status": "unavailable"}
    mock_gw.check_embeddings_status.return_value = {"functional": False, "status": "unavailable"}

    with (
        patch("app.services.gateway.ai_gateway.get_ai_gateway", return_value=mock_gw),
        patch("app.api.routers.health._get_settings", return_value=MagicMock(
            AI_SERVICE_URL="http://ai-svc:5010",
            TENSORZERO_GATEWAY_URL="http://tensorzero:3000",
            SCHEDULER_SERVICE_URL="http://scheduler:5011",
            WORKER_SERVICE_URL="http://worker:5012",
        )),
        patch("app.api.routers.health._probe_http_health", new=AsyncMock(return_value=True)),
    ):
        result = await readiness_check(response=response, db=db)

    assert result["ready"] is False
    assert result["checks"]["llm"] is False


@pytest.mark.asyncio
async def test_readiness_service_dependency_failure_marks_probe_unready():
    db = AsyncMock()
    db.execute = AsyncMock()
    response = _mock_response()

    mock_gw = AsyncMock()
    mock_gw.check_llm_status.return_value = {"available": True, "provider": "openai", "status": "configured: openai"}
    mock_gw.check_embeddings_status.return_value = {"functional": True, "status": "healthy"}

    with (
        patch("app.services.gateway.ai_gateway.get_ai_gateway", return_value=mock_gw),
        patch("app.api.routers.health._get_settings", return_value=MagicMock(
            AI_SERVICE_URL="http://ai-svc:5010",
            TENSORZERO_GATEWAY_URL="http://tensorzero:3000",
            SCHEDULER_SERVICE_URL="http://scheduler:5011",
            WORKER_SERVICE_URL="http://worker:5012",
        )),
        patch(
            "app.api.routers.health._probe_http_health",
            new=AsyncMock(side_effect=[True, True, False, True]),
        ),
    ):
        result = await readiness_check(response=response, db=db)

    assert result["ready"] is False
    assert result["checks"]["scheduler"] is False
    assert response.status_code == 503
