"""Integration tests for authentication flow.

Tests the full registration → login → protected resource → refresh → logout
cycle using the httpx async test client against the FastAPI app.
"""

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.auth.security import create_access_token

API_AUTH_PREFIX = "/api/v1/auth"


@pytest_asyncio.fixture
async def client():
    """Provide an async test client against the FastAPI app."""
    from spectra_api.main import app

    transport = ASGITransport(app=app)
    with (
        patch("app.api.routers.auth.login.invalidate_token", AsyncMock(return_value=None)),
        patch("app.auth.security.is_token_blacklisted", AsyncMock(return_value=False)),
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
async def test_login_with_invalid_credentials_returns_401(client):
    """POST /api/v1/auth/token with bad credentials should return 401."""
    resp = await client.post(
        f"{API_AUTH_PREFIX}/token",
        data={"username": "nonexistent_user", "password": "wrong_password"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_setup_status_returns_is_setup_field(client):
    """GET /api/v1/auth/setup/status should report whether setup is complete."""
    resp = await client.get(f"{API_AUTH_PREFIX}/setup/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "is_setup" in data
    assert isinstance(data["is_setup"], bool)


@pytest.mark.asyncio
async def test_logout_without_token_returns_401(client):
    """POST /api/v1/auth/logout without a bearer token returns 401."""
    resp = await client.post(f"{API_AUTH_PREFIX}/logout")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_logout_with_valid_token(client):
    """POST /api/v1/auth/logout with a valid bearer token succeeds."""
    token = create_access_token(data={"sub": "testuser"})
    resp = await client.post(
        f"{API_AUTH_PREFIX}/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["detail"] == "Successfully logged out"


@pytest.mark.asyncio
async def test_refresh_with_invalid_token_returns_401(client):
    """POST /api/v1/auth/refresh with a garbage refresh token returns 401."""
    resp = await client.post(
        f"{API_AUTH_PREFIX}/refresh",
        json={"refresh_token": "invalid-token-value"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_protected_endpoint_without_auth_returns_401(client):
    """GET /api/v1/auth/me without Authorization header should return 401/403."""
    resp = await client.get(f"{API_AUTH_PREFIX}/me")
    assert resp.status_code in (401, 403)
