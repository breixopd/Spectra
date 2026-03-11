"""Tests for the CVE intelligence API router."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routers.cve import router


def _fake_user(is_superuser: bool = False):
    user = MagicMock()
    user.id = "u-1"
    user.is_superuser = is_superuser
    user.role = "operator"
    return user


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return app


@pytest_asyncio.fixture
async def client():
    app = _make_app()
    from app.api.dependencies import get_current_active_user

    user = _fake_user()
    app.dependency_overrides[get_current_active_user] = lambda: user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
class TestCveLookup:
    async def test_lookup_no_params(self, client):
        resp = await client.get("/api/v1/cve/lookup")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cves"] == []
        assert "Provide at least one" in data["message"]

    async def test_lookup_with_product(self, client):
        cves = [{"id": "CVE-2026-0001", "description": "test vuln"}]
        with patch("app.api.routers.cve.lookup_cves_live", AsyncMock(return_value=cves)):
            resp = await client.get("/api/v1/cve/lookup?product=Apache")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["cves"]) == 1
        assert data["query"]["product"] == "Apache"

    async def test_lookup_with_keyword(self, client):
        with patch("app.api.routers.cve.lookup_cves_live", AsyncMock(return_value=[])):
            resp = await client.get("/api/v1/cve/lookup?keyword=buffer+overflow")
        assert resp.status_code == 200
        assert resp.json()["query"]["keyword"] == "buffer overflow"


@pytest.mark.asyncio
class TestCveExploits:
    async def test_get_exploits_for_cve(self, client):
        modules = [{"name": "exploit/multi/handler", "rank": "excellent"}]
        with patch("app.api.routers.cve.get_metasploit_modules", return_value=modules):
            resp = await client.get("/api/v1/cve/cve/CVE-2026-0001/exploits")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cve_id"] == "CVE-2026-0001"
        assert data["exploit_available"] is True
        assert data["total"] == 1

    async def test_no_exploits_for_cve(self, client):
        with patch("app.api.routers.cve.get_metasploit_modules", return_value=[]):
            resp = await client.get("/api/v1/cve/cve/CVE-2026-9999/exploits")
        assert resp.status_code == 200
        assert resp.json()["exploit_available"] is False

    async def test_invalid_cve_id(self, client):
        resp = await client.get("/api/v1/cve/cve/INVALID/exploits")
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestCveEnriched:
    async def test_enriched_endpoint(self, client):
        enriched = {"cve_id": "CVE-2026-0001", "epss": 0.5, "kev": False}
        mock_db = MagicMock()
        mock_db.enrich = AsyncMock(return_value=enriched)
        with patch("app.services.ai.exploit_db.get_exploit_db", return_value=mock_db):
            resp = await client.get("/api/v1/cve/cve/CVE-2026-0001/enriched")
        assert resp.status_code == 200
        assert resp.json()["cve_id"] == "CVE-2026-0001"


@pytest.mark.asyncio
class TestSearchSploit:
    async def test_searchsploit(self, client):
        results = [{"title": "Apache 2.4 RCE", "edb_id": "12345"}]
        with patch("app.api.routers.cve.search_exploitdb", AsyncMock(return_value=results)), \
             patch("app.api.routers.cve.get_metasploit_modules", return_value=[]):
            resp = await client.get("/api/v1/cve/searchsploit/apache")
        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "apache"
        assert len(data["exploitdb_results"]) == 1

    async def test_searchsploit_long_query(self, client):
        long_query = "a" * 201
        with patch("app.api.routers.cve.search_exploitdb", AsyncMock(return_value=[])), \
             patch("app.api.routers.cve.get_metasploit_modules", return_value=[]):
            resp = await client.get(f"/api/v1/cve/searchsploit/{long_query}")
        assert resp.status_code == 422
