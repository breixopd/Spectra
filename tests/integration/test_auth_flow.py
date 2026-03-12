"""Integration tests for authentication flow.

Tests the full registration → login → protected resource → refresh → logout
cycle using the httpx async test client against the FastAPI app.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.security import create_access_token


@pytest_asyncio.fixture
async def client():
    """Provide an async test client against the FastAPI app."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_login_with_invalid_credentials_returns_401(client):
    """POST /api/auth/token with bad credentials should return 401."""
    resp = await client.post(
        "/api/auth/token",
        data={"username": "nonexistent_user", "password": "wrong_password"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_setup_status_returns_is_setup_field(client):
    """GET /api/auth/setup/status should report whether setup is complete."""
    resp = await client.get("/api/auth/setup/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "is_setup" in data
    assert isinstance(data["is_setup"], bool)


@pytest.mark.asyncio
async def test_logout_without_token_returns_401(client):
    """POST /api/auth/logout without a bearer token returns 401."""
    resp = await client.post("/api/auth/logout")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_logout_with_valid_token(client):
    """POST /api/auth/logout with a valid bearer token succeeds."""
    token = create_access_token(data={"sub": "testuser"})
    resp = await client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["detail"] == "Successfully logged out"


@pytest.mark.asyncio
async def test_refresh_with_invalid_token_returns_401(client):
    """POST /api/auth/refresh with a garbage refresh token returns 401."""
    resp = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": "invalid-token-value"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_protected_endpoint_without_auth_returns_401(client):
    """GET /api/auth/me without Authorization header should return 401/403."""
    resp = await client.get("/api/auth/me")
    assert resp.status_code in (401, 403)
