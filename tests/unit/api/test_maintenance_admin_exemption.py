"""Maintenance middleware: admin API paths stay reachable (aligned /api/v1/admin)."""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_v1_admin_not_blocked_by_maintenance_mode():
    from spectra_api.main import app
    from spectra_platform.core.config import settings

    transport = ASGITransport(app=app)
    with patch.object(settings, "MAINTENANCE_MODE", True):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/admin/monitoring/overview")
    # Must not short-circuit with maintenance JSON before auth runs
    assert resp.status_code == 401
    assert resp.status_code != 503


@pytest.mark.asyncio
async def test_non_admin_api_gets_503_under_maintenance():
    from spectra_api.main import app
    from spectra_platform.core.config import settings

    transport = ASGITransport(app=app)
    with patch.object(settings, "MAINTENANCE_MODE", True):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/targets")
    assert resp.status_code == 503
