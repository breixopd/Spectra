"""Edge-case tests for the data export router: empty data, large datasets, malicious filenames."""

import csv
import json
from datetime import datetime
from io import StringIO
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routers.export import (
    _COLUMNS,
    _VALID_ENTITIES,
    router,
)


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return app


def _fake_user(is_superuser: bool = True) -> MagicMock:
    user = MagicMock()
    user.id = "u-1"
    user.is_superuser = is_superuser
    return user


def _make_row(entity_type: str, **overrides):
    defaults = {
        "missions": {
            "id": "m-1",
            "target": "192.168.1.1",
            "directive": "scan",
            "status": "active",
            "created_at": datetime(2026, 1, 1),
        },
        "findings": {
            "id": "f-1",
            "target_id": "t-1",
            "title": "XSS",
            "description": "desc",
            "severity": "high",
            "status": "open",
            "cvss_score": 7.5,
            "cve_id": "CVE-2026-001",
            "tool_source": "nmap",
            "created_at": datetime(2026, 1, 1),
        },
        "targets": {
            "id": "t-1",
            "address": "10.0.0.1",
            "description": "web",
            "status": "scanned",
            "os": "Linux",
            "created_at": datetime(2026, 1, 1),
        },
        "exploits": {
            "id": "e-1",
            "target_id": "t-1",
            "name": "rce",
            "type": "remote",
            "success": True,
            "output": "shell",
            "timestamp": datetime(2026, 1, 1),
        },
    }
    vals = {**defaults[entity_type], **overrides}
    row = MagicMock()
    for k, v in vals.items():
        setattr(row, k, v)
    return row


@pytest_asyncio.fixture
async def client():
    """Async test client with mocked auth and DB returning empty results."""
    app = _make_app()

    from app.api.dependencies import get_current_active_user
    from app.core.database import get_async_session

    user = _fake_user()
    app.dependency_overrides[get_current_active_user] = lambda: user

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def _get_session():
        yield mock_session

    app.dependency_overrides[get_async_session] = _get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, mock_session, user


# ---------------------------------------------------------------------------
# Export with no data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExportNoData:
    """Verify correct responses when the DB returns zero rows."""

    async def test_json_export_returns_empty_list(self, client):
        ac, _, _ = client
        resp = await ac.get("/api/v1/export/missions?format=json")
        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert data == []

    async def test_csv_export_returns_header_only(self, client):
        ac, _, _ = client
        resp = await ac.get("/api/v1/export/findings?format=csv")
        assert resp.status_code == 200
        lines = resp.text.strip().split("\n")
        assert len(lines) == 1  # header row only

    async def test_empty_json_has_correct_content_type(self, client):
        ac, _, _ = client
        resp = await ac.get("/api/v1/export/targets?format=json")
        assert "application/json" in resp.headers["content-type"]

    async def test_empty_csv_has_correct_content_type(self, client):
        ac, _, _ = client
        resp = await ac.get("/api/v1/export/exploits?format=csv")
        assert "text/csv" in resp.headers["content-type"]

    async def test_empty_export_all_entity_types(self, client):
        ac, _, _ = client
        for entity in _VALID_ENTITIES:
            for fmt in ("json", "csv"):
                resp = await ac.get(f"/api/v1/export/{entity}?format={fmt}")
                assert resp.status_code == 200, f"{entity}/{fmt} failed"


# ---------------------------------------------------------------------------
# Large dataset (mocked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExportLargeDataset:
    """Ensure export handles many rows without error."""

    async def test_json_export_1000_rows(self, client):
        ac, session, _ = client
        rows = [_make_row("missions", id=f"m-{i}") for i in range(1000)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = rows
        session.execute = AsyncMock(return_value=mock_result)

        resp = await ac.get("/api/v1/export/missions?format=json")
        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert len(data) == 1000

    async def test_csv_export_1000_rows(self, client):
        ac, session, _ = client
        rows = [_make_row("findings", id=f"f-{i}") for i in range(1000)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = rows
        session.execute = AsyncMock(return_value=mock_result)

        resp = await ac.get("/api/v1/export/findings?format=csv")
        assert resp.status_code == 200
        reader = csv.reader(StringIO(resp.text))
        all_rows = list(reader)
        # 1 header + 1000 data rows
        assert len(all_rows) == 1001

    async def test_large_export_preserves_field_order(self, client):
        ac, session, _ = client
        rows = [_make_row("targets", id=f"t-{i}") for i in range(100)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = rows
        session.execute = AsyncMock(return_value=mock_result)

        resp = await ac.get("/api/v1/export/targets?format=csv")
        reader = csv.reader(StringIO(resp.text))
        header = next(reader)
        assert header == _COLUMNS["targets"]


# ---------------------------------------------------------------------------
# Malicious filename injection in CSV export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExportMaliciousFilename:
    """Verify entity_type is validated so it can't inject into Content-Disposition."""

    async def test_path_traversal_entity_type_rejected(self, client):
        ac, _, _ = client
        resp = await ac.get("/api/v1/export/../../etc/passwd?format=csv")
        assert resp.status_code in (400, 404, 422)

    async def test_entity_with_semicolon_rejected(self, client):
        ac, _, _ = client
        resp = await ac.get("/api/v1/export/missions;malicious?format=csv")
        assert resp.status_code in (400, 404, 422)

    async def test_entity_with_newline_rejected(self, client):
        ac, _, _ = client
        resp = await ac.get("/api/v1/export/missions%0d%0aInjected: header?format=csv")
        assert resp.status_code in (400, 404, 422)

    async def test_only_valid_entities_pass(self, client):
        ac, _, _ = client
        # Note: "missions/../targets" resolves via URL normalization to a valid
        # entity path (/api/v1/targets), so it's not included here.
        for entity in ("__import__", "os.system", "<script>"):
            resp = await ac.get(f"/api/v1/export/{entity}?format=csv")
            assert resp.status_code in (400, 404, 422), f"{entity!r} should be rejected"

    async def test_valid_entity_filename_is_safe(self, client):
        ac, _, _ = client
        resp = await ac.get("/api/v1/export/missions?format=csv")
        assert resp.status_code == 200
        disposition = resp.headers.get("content-disposition", "")
        assert "spectra_missions.csv" in disposition
        # No path separators in the filename
        assert "/" not in disposition.split("filename=")[-1]
        assert "\\" not in disposition.split("filename=")[-1]
