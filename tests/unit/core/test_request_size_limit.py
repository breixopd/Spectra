"""Unit tests for the request body size limit middleware.

Validates that the http middleware in spectra_api.factory rejects oversized
requests with 413 and passes normal-sized requests through.
"""

import json
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def client():
    from spectra_api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_oversized_request_rejected_with_413(client):
    """A request declaring content-length above MAX_REQUEST_BODY_SIZE gets 413."""
    from spectra_common.config import settings

    oversized = settings.MAX_REQUEST_BODY_SIZE + 1
    resp = await client.post(
        "/api/v1/health",
        content=b"x",
        headers={"Content-Length": str(oversized)},
    )
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_normal_request_passes_through(client):
    """A small GET request is not blocked by the size limiter."""
    resp = await client.get("/api/v1/health")
    assert resp.status_code in (200, 503)  # 503 if db is down, but not 413


@pytest.mark.asyncio
async def test_request_at_exact_limit_passes(client):
    """A request whose content-length equals the limit should pass."""
    from spectra_common.config import settings

    resp = await client.post(
        "/api/v1/health",
        content=b"x",
        headers={"Content-Length": str(settings.MAX_REQUEST_BODY_SIZE)},
    )
    # Should NOT be 413 — it's at the limit, not above
    assert resp.status_code != 413


@pytest.mark.asyncio
async def test_configurable_limit():
    """The limit comes from settings.MAX_REQUEST_BODY_SIZE and is configurable."""
    from spectra_common.config import settings

    assert hasattr(settings, "MAX_REQUEST_BODY_SIZE")
    assert isinstance(settings.MAX_REQUEST_BODY_SIZE, int)
    assert settings.MAX_REQUEST_BODY_SIZE > 0


@pytest.mark.asyncio
async def test_api_429_handler_preserves_non_slowapi_detail_and_headers():
    """Non-SlowAPI 429 responses should keep their original detail and headers."""
    from spectra_api.errors import make_error_handler
    from spectra_api.templates import templates

    request = MagicMock()
    request.url.path = "/api/test"

    handler = make_error_handler(templates, 429, "Too many requests", "errors/429.html")
    exc = HTTPException(
        status_code=429,
        detail={"detail": "Hourly API limit reached: 100/100", "error_code": "RATE_LIMITED", "status": 429},
        headers={"Retry-After": "1800"},
    )

    response = await handler(request, exc)

    assert response.status_code == 429
    assert response.headers.get("Retry-After") == "1800"
    assert response.headers.get("X-RateLimit-Limit") is None
    body = json.loads(response.body)
    assert body["status_code"] == 429
    assert "RATE_LIMITED" in body["detail"]
    assert "Hourly API limit reached" in body["detail"]
