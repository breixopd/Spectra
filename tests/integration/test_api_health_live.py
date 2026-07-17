"""Real health endpoint integration test — requires running app.

This test asserts that /api/health returns 200 with real dependencies
when run against a live Spectra instance (e.g. inside the compose stack).
"""

import os

import httpx
import pytest

BASE_URL = os.environ.get("APP_BASE_URL", "http://app:5000")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("APP_BASE_URL"),
        reason="APP_BASE_URL not set — requires running app",
    ),
]


@pytest.mark.asyncio
async def test_health_endpoint_live():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("healthy", "ok", "degraded")
        assert data["service"] == "spectra"
        assert "version" in data
        assert "components" in data
