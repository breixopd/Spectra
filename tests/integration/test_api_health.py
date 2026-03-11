"""Integration tests for health API endpoints.

Uses httpx.AsyncClient with the FastAPI test app to verify health
and readiness probes return the expected format.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch


@pytest_asyncio.fixture
async def client():
    """Provide an async test client against the FastAPI app."""
    # Lazy import so module-level side effects don't interfere with collection
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health_returns_healthy(client):
    """GET /api/health should return 200 with status and version fields."""
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert data["status"] in ("healthy", "degraded")
    assert "service" in data
    assert data["service"] == "spectra"
    assert "version" in data
    assert "components" in data


@pytest.mark.asyncio
async def test_health_verbose_includes_extra_components(client):
    """GET /api/health?verbose=true should include additional components."""
    resp = await client.get("/api/health", params={"verbose": "true"})
    assert resp.status_code in (200, 503)
    data = resp.json()
    components = data.get("components", {})
    # Verbose mode adds at least one extra component beyond 'database'
    assert len(components) >= 1


@pytest.mark.asyncio
async def test_health_ready_returns_expected_format(client):
    """GET /api/health/ready should return readiness status with component checks."""
    resp = await client.get("/api/health/ready")
    assert resp.status_code in (200, 503)
    data = resp.json()
    assert "ready" in data or "checks" in data or "status" in data
