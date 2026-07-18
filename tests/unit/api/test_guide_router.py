"""Authenticated help and API documentation pages."""

from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from spectra_api.api.dependencies import get_current_active_user
from spectra_api.ui.guide import router


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(
        id="test-user",
        username="test-user",
        is_active=True,
    )
    return app


@pytest_asyncio.fixture
async def client():
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_help_page_is_authenticated_and_renders(client):
    response = await client.get("/help")

    assert response.status_code == 200
    assert "Getting Started" in response.text
    assert "API Documentation" in response.text


@pytest.mark.asyncio
async def test_api_docs_page_is_authenticated_and_points_to_private_schema(client):
    response = await client.get("/docs/api")

    assert response.status_code == 200
    assert "API Documentation" in response.text
    assert "/docs/api/openapi.json" in response.text


@pytest.mark.asyncio
async def test_private_openapi_schema_is_available_to_authenticated_users(client):
    response = await client.get("/docs/api/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "FastAPI"


@pytest.mark.asyncio
async def test_guide_pages_require_authentication():
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/help")

    assert response.status_code == 401
