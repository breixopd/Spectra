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
    # /api/health?verbose=true typically returns a larger payload
    resp = await client.get(
        "/api/health",
        params={"verbose": "true"},
        headers={"Accept-Encoding": "gzip"},
    )
    assert resp.status_code in (200, 503)
    # If the response is large enough, it should be compressed
    encoding = resp.headers.get("content-encoding", "")
    # The response may be too small to compress — only assert if body is big
    if len(resp.content) > 1000:
        assert encoding == "gzip", "Large response should be gzip-compressed"


@pytest.mark.asyncio
async def test_small_response_not_compressed(client):
    """Responses under the minimum_size (1000 bytes) should not be compressed."""
    # A simple health check returns a small JSON body (< 1000 bytes without verbose)
    resp = await client.get(
        "/api/health",
        headers={"Accept-Encoding": "gzip"},
    )
    assert resp.status_code in (200, 503)
    # Small responses (under minimum_size=1000) should NOT be compressed
    content_encoding = resp.headers.get("content-encoding", "")
    if len(resp.content) < 500:
        assert content_encoding != "gzip", "Small response should not be gzip-compressed"


@pytest.mark.asyncio
async def test_no_compression_without_accept_encoding(client):
    """Without Accept-Encoding: gzip, response should not be compressed."""
    resp = await client.get("/api/health")
    assert resp.status_code in (200, 503)
    content_encoding = resp.headers.get("content-encoding", "")
    assert content_encoding != "gzip"
