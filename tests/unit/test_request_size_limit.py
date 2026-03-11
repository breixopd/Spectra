"""Unit tests for the request body size limit middleware.

Validates that the http middleware in app.main rejects oversized
requests with 413 and passes normal-sized requests through.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def client():
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_oversized_request_rejected_with_413(client):
    """A request declaring content-length above MAX_REQUEST_BODY_SIZE gets 413."""
    from app.core.config import settings

    oversized = settings.MAX_REQUEST_BODY_SIZE + 1
    resp = await client.post(
        "/api/health",
        content=b"x",
        headers={"Content-Length": str(oversized)},
    )
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_normal_request_passes_through(client):
    """A small GET request is not blocked by the size limiter."""
    resp = await client.get("/api/health")
    assert resp.status_code in (200, 503)  # 503 if db is down, but not 413


@pytest.mark.asyncio
async def test_request_at_exact_limit_passes(client):
    """A request whose content-length equals the limit should pass."""
    from app.core.config import settings

    resp = await client.post(
        "/api/health",
        content=b"x",
        headers={"Content-Length": str(settings.MAX_REQUEST_BODY_SIZE)},
    )
    # Should NOT be 413 — it's at the limit, not above
    assert resp.status_code != 413


@pytest.mark.asyncio
async def test_configurable_limit():
    """The limit comes from settings.MAX_REQUEST_BODY_SIZE and is configurable."""
    from app.core.config import settings

    assert hasattr(settings, "MAX_REQUEST_BODY_SIZE")
    assert isinstance(settings.MAX_REQUEST_BODY_SIZE, int)
    assert settings.MAX_REQUEST_BODY_SIZE > 0
