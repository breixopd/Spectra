"""Deep tests for the health check router (/api/health)."""

from unittest.mock import AsyncMock, MagicMock, patch

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


# ---------------------------------------------------------------------------
# GET /health — basic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_returns_healthy_when_db_ok():
    db = AsyncMock()
    db.execute = AsyncMock()
    response = _mock_response()

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

    result = await health_check(request=_mock_request(), response=response, db=db, verbose=False)

    assert "embeddings" not in result["components"]
    assert "llm" not in result["components"]
    assert "cache" not in result["components"]
    assert "disk" not in result["components"]


# ---------------------------------------------------------------------------
# GET /health?verbose=true — component details
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_verbose_includes_embeddings():
    db = AsyncMock()
    db.execute = AsyncMock()
    response = _mock_response()

    mock_rag = MagicMock()
    mock_rag.is_functional = True

    with patch("app.api.routers.health.RAGService", return_value=mock_rag, create=True):
        # Patch the inline import

        with patch.dict("sys.modules", {"app.services.ai.rag": MagicMock(RAGService=lambda: mock_rag)}):
            with (
                patch("app.api.routers.health._extract_request_token", return_value=("tok", "header")),
                patch("app.api.routers.health._decode_access_payload", return_value={"sub": "u-1"}),
                patch("app.api.routers.health._load_active_user_from_payload_with_session", new_callable=AsyncMock, return_value=MagicMock()),
            ):
                result = await health_check(request=_mock_request(), response=response, db=db, verbose=True)

    assert "embeddings" in result["components"]


@pytest.mark.asyncio
async def test_health_verbose_includes_llm():
    db = AsyncMock()
    db.execute = AsyncMock()
    response = _mock_response()

    mock_router = MagicMock()
    mock_router.provider = "openai"

    mock_rag = MagicMock()
    mock_rag.is_functional = False

    mock_cache = MagicMock()
    mock_cache.get_stats.return_value = {"hit_rate_percent": 85}

    mock_pool = MagicMock()
    mock_pool.available = True

    with patch.dict(
        "sys.modules",
        {
            "app.services.ai.rag": MagicMock(RAGService=lambda: mock_rag),
            "app.services.ai.router": MagicMock(get_smart_router=lambda: mock_router),
            "app.core.cache": MagicMock(get_cache=lambda: mock_cache),
            "app.services.tools.sandbox": MagicMock(get_sandbox_pool=lambda: mock_pool),
        },
    ):
        with (
            patch("app.api.routers.health._extract_request_token", return_value=("tok", "header")),
            patch("app.api.routers.health._decode_access_payload", return_value={"sub": "u-1"}),
            patch("app.api.routers.health._load_active_user_from_payload_with_session", new_callable=AsyncMock, return_value=MagicMock()),
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

    mock_rag = MagicMock()
    mock_rag.is_functional = False

    with patch.dict(
        "sys.modules",
        {
            "app.services.ai.rag": MagicMock(RAGService=lambda: mock_rag),
            "app.services.ai.router": MagicMock(get_smart_router=MagicMock(side_effect=RuntimeError("no LLM"))),
            "app.core.cache": MagicMock(get_cache=lambda: mock_cache),
            "app.services.tools.sandbox": MagicMock(get_sandbox_pool=lambda: None),
        },
    ):
        with (
            patch("app.api.routers.health._extract_request_token", return_value=("tok", "header")),
            patch("app.api.routers.health._decode_access_payload", return_value={"sub": "u-1"}),
            patch("app.api.routers.health._load_active_user_from_payload_with_session", new_callable=AsyncMock, return_value=MagicMock()),
        ):
            result = await health_check(request=_mock_request(), response=response, db=db, verbose=True)

    assert result["components"]["cache"]["status"] == "healthy"
    assert result["components"]["cache"]["hit_rate_percent"] == 42


@pytest.mark.asyncio
async def test_health_verbose_cache_unavailable():
    db = AsyncMock()
    db.execute = AsyncMock()
    response = _mock_response()

    mock_rag = MagicMock()
    mock_rag.is_functional = False

    with patch.dict(
        "sys.modules",
        {
            "app.services.ai.rag": MagicMock(RAGService=lambda: mock_rag),
            "app.services.ai.router": MagicMock(get_smart_router=MagicMock(side_effect=RuntimeError)),
            "app.core.cache": MagicMock(get_cache=lambda: None),
            "app.services.tools.sandbox": MagicMock(get_sandbox_pool=MagicMock(side_effect=RuntimeError)),
        },
    ):
        with (
            patch("app.api.routers.health._extract_request_token", return_value=("tok", "header")),
            patch("app.api.routers.health._decode_access_payload", return_value={"sub": "u-1"}),
            patch("app.api.routers.health._load_active_user_from_payload_with_session", new_callable=AsyncMock, return_value=MagicMock()),
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

    mock_rag = MagicMock()
    mock_rag.is_functional = False

    with patch.dict(
        "sys.modules",
        {
            "app.services.ai.rag": MagicMock(RAGService=lambda: mock_rag),
            "app.services.ai.router": MagicMock(get_smart_router=MagicMock(side_effect=RuntimeError)),
            "app.core.cache": MagicMock(get_cache=lambda: None),
            "app.services.tools.sandbox": MagicMock(get_sandbox_pool=MagicMock(side_effect=RuntimeError)),
        },
    ):
        with patch("app.api.routers.health.shutil.disk_usage", return_value=mock_usage):
            with (
                patch("app.api.routers.health._extract_request_token", return_value=("tok", "header")),
                patch("app.api.routers.health._decode_access_payload", return_value={"sub": "u-1"}),
                patch("app.api.routers.health._load_active_user_from_payload_with_session", new_callable=AsyncMock, return_value=MagicMock()),
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

    mock_rag = MagicMock()
    mock_rag.is_functional = True
    mock_router = MagicMock()

    with patch.dict(
        "sys.modules",
        {
            "app.services.ai.rag": MagicMock(RAGService=lambda: mock_rag),
            "app.services.ai.router": MagicMock(get_smart_router=lambda: mock_router),
        },
    ):
        result = await readiness_check(response=response, db=db)

    assert result["ready"] is True
    assert result["checks"]["database"] is True


@pytest.mark.asyncio
async def test_readiness_db_down():
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=OSError("db down"))
    response = _mock_response()

    mock_rag = MagicMock()
    mock_rag.is_functional = True

    with patch.dict(
        "sys.modules",
        {
            "app.services.ai.rag": MagicMock(RAGService=lambda: mock_rag),
            "app.services.ai.router": MagicMock(get_smart_router=lambda: MagicMock()),
        },
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

    with patch.dict(
        "sys.modules",
        {
            "app.services.ai.rag": MagicMock(RAGService=MagicMock(side_effect=RuntimeError)),
            "app.services.ai.router": MagicMock(get_smart_router=MagicMock(side_effect=RuntimeError)),
        },
    ):
        result = await readiness_check(response=response, db=db)

    assert result["ready"] is False
    assert result["checks"]["llm"] is False
