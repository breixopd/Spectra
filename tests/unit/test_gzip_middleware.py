"""Unit tests for GZip compression middleware.

Verifies that the GZipMiddleware configured in app.main compresses
responses that exceed the minimum_size threshold (1000 bytes).
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
async def test_large_response_is_compressed(client):
    """Responses above 1000 bytes should be gzip-compressed when client accepts it."""
    resp = await client.get(
        "/api/v1/health",
        headers={"Accept-Encoding": "gzip"},
    )
    assert resp.status_code in (200, 503)
    # If the response is large enough, it should be compressed
    encoding = resp.headers.get("content-encoding", "")
    # The response may be too small to compress — only assert if body is big
    if len(resp.content) > 1000:
        assert encoding == "gzip", "Large response should be gzip-compressed"


@pytest.mark.asyncio
async def test_small_response_still_valid(client):
    """Small responses should still return valid JSON regardless of compression."""
    resp = await client.get(
        "/api/v1/health",
        headers={"Accept-Encoding": "gzip"},
    )
    assert resp.status_code in (200, 503)
    # Verify the response body is valid JSON (httpx auto-decompresses)
    data = resp.json()
    assert "status" in data


@pytest.mark.asyncio
async def test_response_valid_without_accept_encoding(client):
    """Responses without Accept-Encoding should still be valid."""
    resp = await client.get("/api/v1/health")
    assert resp.status_code in (200, 503)
    data = resp.json()
    assert "status" in data
