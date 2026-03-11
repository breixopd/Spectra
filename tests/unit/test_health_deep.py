"""Deep tests for the health check router (/api/health)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.routers.health import health_check, readiness_check


def _mock_response():
    resp = MagicMock()
    resp.status_code = 200
    return resp


# ---------------------------------------------------------------------------
# GET /health — basic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_returns_healthy_when_db_ok():
    db = AsyncMock()
    db.execute = AsyncMock()
    response = _mock_response()

    result = await health_check(response=response, db=db, verbose=False)

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

    result = await health_check(response=response, db=db, verbose=False)

    assert result["status"] == "degraded"
    assert result["components"]["database"]["status"] == "unhealthy"
    assert result["components"]["database"]["error"] == "ConnectionError"
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_health_non_verbose_excludes_extras():
    db = AsyncMock()
    db.execute = AsyncMock()
    response = _mock_response()

    result = await health_check(response=response, db=db, verbose=False)

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
            result = await health_check(response=response, db=db, verbose=True)

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

    with patch.dict("sys.modules", {
        "app.services.ai.rag": MagicMock(RAGService=lambda: mock_rag),
        "app.services.ai.router": MagicMock(get_smart_router=lambda: mock_router),
        "app.core.cache": MagicMock(get_cache=lambda: mock_cache),
        "app.services.tools.sandbox": MagicMock(get_sandbox_pool=lambda: mock_pool),
    }):
        result = await health_check(response=response, db=db, verbose=True)

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

    with patch.dict("sys.modules", {
        "app.services.ai.rag": MagicMock(RAGService=lambda: mock_rag),
        "app.services.ai.router": MagicMock(get_smart_router=MagicMock(side_effect=Exception("no LLM"))),
        "app.core.cache": MagicMock(get_cache=lambda: mock_cache),
        "app.services.tools.sandbox": MagicMock(get_sandbox_pool=lambda: None),
    }):
        result = await health_check(response=response, db=db, verbose=True)

    assert result["components"]["cache"]["status"] == "healthy"
    assert result["components"]["cache"]["hit_rate_percent"] == 42


@pytest.mark.asyncio
async def test_health_verbose_cache_unavailable():
    db = AsyncMock()
    db.execute = AsyncMock()
    response = _mock_response()

    mock_rag = MagicMock()
    mock_rag.is_functional = False

    with patch.dict("sys.modules", {
        "app.services.ai.rag": MagicMock(RAGService=lambda: mock_rag),
        "app.services.ai.router": MagicMock(get_smart_router=MagicMock(side_effect=Exception)),
        "app.core.cache": MagicMock(get_cache=lambda: None),
        "app.services.tools.sandbox": MagicMock(get_sandbox_pool=MagicMock(side_effect=Exception)),
    }):
        result = await health_check(response=response, db=db, verbose=True)

    assert result["components"]["cache"]["status"] == "unavailable"


@pytest.mark.asyncio
async def test_health_verbose_disk_info():
    db = AsyncMock()
    db.execute = AsyncMock()
    response = _mock_response()

    mock_usage = MagicMock()
    mock_usage.free = 50 * (1024 ** 3)
    mock_usage.total = 100 * (1024 ** 3)
    mock_usage.used = 50 * (1024 ** 3)

    mock_rag = MagicMock()
    mock_rag.is_functional = False

    with patch.dict("sys.modules", {
        "app.services.ai.rag": MagicMock(RAGService=lambda: mock_rag),
        "app.services.ai.router": MagicMock(get_smart_router=MagicMock(side_effect=Exception)),
        "app.core.cache": MagicMock(get_cache=lambda: None),
        "app.services.tools.sandbox": MagicMock(get_sandbox_pool=MagicMock(side_effect=Exception)),
    }):
        with patch("app.api.routers.health.shutil.disk_usage", return_value=mock_usage):
            result = await health_check(response=response, db=db, verbose=True)

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

    with patch.dict("sys.modules", {
        "app.services.ai.rag": MagicMock(RAGService=lambda: mock_rag),
        "app.services.ai.router": MagicMock(get_smart_router=lambda: mock_router),
    }):
        result = await readiness_check(response=response, db=db)

    assert result["ready"] is True
    assert result["checks"]["database"] is True


@pytest.mark.asyncio
async def test_readiness_db_down():
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=Exception("db down"))
    response = _mock_response()

    mock_rag = MagicMock()
    mock_rag.is_functional = True

    with patch.dict("sys.modules", {
        "app.services.ai.rag": MagicMock(RAGService=lambda: mock_rag),
        "app.services.ai.router": MagicMock(get_smart_router=lambda: MagicMock()),
    }):
        result = await readiness_check(response=response, db=db)

    assert result["ready"] is False
    assert result["checks"]["database"] is False
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_readiness_llm_unavailable():
    db = AsyncMock()
    db.execute = AsyncMock()
    response = _mock_response()

    with patch.dict("sys.modules", {
        "app.services.ai.rag": MagicMock(RAGService=MagicMock(side_effect=Exception)),
        "app.services.ai.router": MagicMock(get_smart_router=MagicMock(side_effect=Exception)),
    }):
        result = await readiness_check(response=response, db=db)

    assert result["ready"] is False
    assert result["checks"]["llm"] is False
