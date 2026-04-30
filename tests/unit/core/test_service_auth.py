"""Tests for app.di.service_auth module."""

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.di.service_auth import ServiceAuthMiddleware


def _make_app(secret: str = "test-secret") -> FastAPI:
    """Build a minimal FastAPI app with ServiceAuthMiddleware."""
    app = FastAPI()
    app.add_middleware(ServiceAuthMiddleware, secret=secret)

    @app.get("/internal")
    async def internal_endpoint():
        return {"status": "ok"}

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    @app.get("/healthz")
    async def healthz():
        return {"status": "healthy"}

    return app


@pytest.mark.asyncio
async def test_valid_token_passes():
    app = _make_app("my-secret")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/internal", headers={"X-Service-Auth": "my-secret"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_invalid_token_rejected():
    app = _make_app("my-secret")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with pytest.raises(HTTPException) as exc_info:
            await client.get("/internal", headers={"X-Service-Auth": "wrong-secret"})
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_missing_header_rejected():
    app = _make_app("my-secret")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with pytest.raises(HTTPException) as exc_info:
            await client.get("/internal")
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_empty_header_rejected():
    app = _make_app("my-secret")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with pytest.raises(HTTPException) as exc_info:
            await client.get("/internal", headers={"X-Service-Auth": ""})
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_health_endpoint_bypasses_auth():
    app = _make_app("my-secret")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_healthz_endpoint_bypasses_auth():
    app = _make_app("my-secret")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_no_secret_configured_denies_non_health():
    """When no secret is set, non-health routes fail closed."""
    app = _make_app(secret="")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with pytest.raises(HTTPException) as exc_info:
            await client.get("/internal")
        assert exc_info.value.status_code == 401
        assert "not configured" in (exc_info.value.detail or "").lower()


@pytest.mark.asyncio
async def test_no_secret_health_endpoints_still_public():
    app = _make_app(secret="")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/healthz")).status_code == 200


@pytest.mark.asyncio
async def test_tampered_token_rejected():
    """A token differing by one character is rejected."""
    app = _make_app("correct-token-value")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with pytest.raises(HTTPException) as exc_info:
            await client.get("/internal", headers={"X-Service-Auth": "correct-token-valuf"})
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_timing_safe_comparison():
    """Verify the middleware uses hmac.compare_digest (constant-time)."""
    import hmac as hmac_mod
    from unittest.mock import patch

    app = _make_app("secret")
    with patch.object(hmac_mod, "compare_digest", wraps=hmac_mod.compare_digest) as spy:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get("/internal", headers={"X-Service-Auth": "secret"})
        spy.assert_called_once()
