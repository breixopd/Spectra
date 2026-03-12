"""Live API tests — requires running Spectra instance.

Run with: pytest tests/e2e/test_api_live.py -v
Requires APP_BASE_URL environment variable.
"""

import os

import httpx
import pytest

BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5000")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.skipif(not os.environ.get("APP_BASE_URL"), reason="APP_BASE_URL not set"),
]


@pytest.fixture
async def client():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as c:
        yield c


@pytest.fixture
async def auth_client(client):
    """Authenticated client — logs in and returns client with auth headers."""
    resp = await client.post(
        "/api/auth/login",
        json={
            "username": os.environ.get("TEST_USERNAME", "admin"),
            "password": os.environ.get("TEST_PASSWORD", "admin"),
        },
    )
    if resp.status_code != 200:
        pytest.skip("Cannot authenticate — check TEST_USERNAME/TEST_PASSWORD")
    token = resp.json().get("access_token") or resp.cookies.get("access_token")
    if token:
        client.headers["Authorization"] = f"Bearer {token}"
    return client


async def test_health_endpoint(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("healthy", "ok")


async def test_api_docs_page(auth_client):
    resp = await auth_client.get("/docs/api")
    assert resp.status_code == 200
    assert "API Documentation" in resp.text


async def test_help_page(auth_client):
    resp = await auth_client.get("/help")
    assert resp.status_code == 200
    assert "Getting Started" in resp.text


async def test_dashboard_loads(auth_client):
    resp = await auth_client.get("/dashboard")
    assert resp.status_code == 200


async def test_system_settings_api(auth_client):
    resp = await auth_client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "ai_provider" in data


async def test_service_topology(auth_client):
    resp = await auth_client.get("/api/admin/system/services")
    assert resp.status_code == 200


async def test_server_pool_crud(auth_client):
    """Full CRUD cycle on server pool."""
    # Create
    resp = await auth_client.post(
        "/api/admin/servers",
        json={
            "name": "e2e-test-worker",
            "service_type": "sandbox_worker",
            "url": "http://test.invalid:8080",
        },
    )
    assert resp.status_code == 201
    node = resp.json()
    node_id = node["id"]

    # List
    resp = await auth_client.get("/api/admin/servers")
    assert resp.status_code == 200
    assert any(n["id"] == node_id for n in resp.json())

    # Update
    resp = await auth_client.patch(
        f"/api/admin/servers/{node_id}",
        json={
            "weight": 5,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["weight"] == 5

    # Delete
    resp = await auth_client.delete(f"/api/admin/servers/{node_id}")
    assert resp.status_code == 200
