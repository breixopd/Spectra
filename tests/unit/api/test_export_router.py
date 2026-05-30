"""
Tests for the data export API router.

Covers JSON/CSV export, date filtering, invalid entities,
unauthorized access, and CSV injection protection.
"""

import csv
import json
from datetime import datetime
from io import StringIO
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from spectra_api.api.routers.export import (
    _CSV_INJECTION_CHARS,
    _VALID_ENTITIES,
    _row_to_dict,
    _sanitize_csv_value,
    router,
)

# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


class TestSanitizeCsvValue:
    """Tests for CSV injection sanitization."""

    @pytest.mark.parametrize("char", list(_CSV_INJECTION_CHARS))
    def test_prefixes_dangerous_first_char(self, char: str):
        dangerous = f"{char}cmd('calc')"
        result = _sanitize_csv_value(dangerous)
        assert result.startswith("'"), f"Expected leading quote for char {char!r}"

    def test_safe_value_unchanged(self):
        assert _sanitize_csv_value("hello world") == "hello world"

    def test_none_becomes_empty(self):
        assert _sanitize_csv_value(None) == ""

    def test_empty_string_unchanged(self):
        assert _sanitize_csv_value("") == ""

    def test_numeric_value(self):
        assert _sanitize_csv_value(42) == "42"

    def test_equals_sign_sanitized(self):
        assert _sanitize_csv_value("=1+2") == "'=1+2"

    def test_plus_sign_sanitized(self):
        assert _sanitize_csv_value("+cmd") == "'+cmd"

    def test_at_sign_sanitized(self):
        assert _sanitize_csv_value("@SUM(A1)") == "'@SUM(A1)"

    def test_tab_sanitized(self):
        assert _sanitize_csv_value("\tcmd") == "'\tcmd"


class TestRowToDict:
    """Tests for row-to-dict conversion."""

    def test_basic_attributes(self):
        row = MagicMock()
        row.id = "abc"
        row.name = "test"
        result = _row_to_dict(row, ["id", "name"])
        assert result == {"id": "abc", "name": "test"}

    def test_datetime_converted_to_isoformat(self):
        row = MagicMock()
        dt = datetime(2026, 1, 15, 10, 30, 0)
        row.created_at = dt
        result = _row_to_dict(row, ["created_at"])
        assert result["created_at"] == "2026-01-15T10:30:00"

    def test_enum_value_extracted(self):
        row = MagicMock()
        enum_val = MagicMock()
        enum_val.value = "critical"
        row.severity = enum_val
        result = _row_to_dict(row, ["severity"])
        assert result["severity"] == "critical"

    def test_missing_attribute_returns_none(self):
        row = MagicMock(spec=[])  # no attributes
        result = _row_to_dict(row, ["nonexistent"])
        assert result["nonexistent"] is None


# ---------------------------------------------------------------------------
# Integration-style tests via TestClient
# ---------------------------------------------------------------------------


def _make_app() -> FastAPI:
    """Build a minimal FastAPI app with the export router mounted."""
    from spectra_auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    limiter.enabled = False  # Disable rate limiting in tests
    app.include_router(router, prefix="/api/v1")
    return app


def _fake_user(is_superuser: bool = True) -> MagicMock:
    user = MagicMock()
    user.id = "u-1"
    user.is_superuser = is_superuser
    return user


def _make_row(entity_type: str, **overrides):
    """Create a mock DB row for the given entity type."""
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
            "description": "reflected",
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
    # Make sure spec doesn't interfere with getattr
    return row


@pytest_asyncio.fixture
async def client():
    """Provide an async test client with mocked auth and DB."""
    app = _make_app()

    # Override auth dependency
    from spectra_api.api.dependencies import get_current_active_user
    from spectra_persistence.database import get_async_session

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


@pytest.mark.asyncio
class TestExportEndpoint:
    """Tests for GET /api/export/{entity_type}."""

    async def test_json_export_empty(self, client):
        ac, _session, _user = client
        resp = await ac.get("/api/v1/export/missions?format=json")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        data = json.loads(resp.content)
        assert isinstance(data, list)

    async def test_csv_export_empty(self, client):
        ac, _session, _user = client
        resp = await ac.get("/api/v1/export/findings?format=csv")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        reader = csv.reader(StringIO(resp.text))
        header = next(reader)
        assert "id" in header

    async def test_json_export_with_rows(self, client):
        ac, session, _user = client
        row = _make_row("missions")
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [row]
        session.execute = AsyncMock(return_value=mock_result)

        resp = await ac.get("/api/v1/export/missions?format=json")
        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert len(data) == 1
        assert data[0]["id"] == "m-1"

    async def test_csv_export_with_rows(self, client):
        ac, session, _user = client
        row = _make_row("findings")
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [row]
        session.execute = AsyncMock(return_value=mock_result)

        resp = await ac.get("/api/v1/export/findings?format=csv")
        assert resp.status_code == 200
        reader = csv.reader(StringIO(resp.text))
        header = next(reader)
        data_row = next(reader)
        assert header[0] == "id"
        assert data_row[0] == "f-1"

    async def test_invalid_entity_type(self, client):
        ac, _session, _user = client
        resp = await ac.get("/api/v1/export/invalid_type?format=json")
        assert resp.status_code == 400

    async def test_invalid_format(self, client):
        ac, _session, _user = client
        resp = await ac.get("/api/v1/export/missions?format=xml")
        assert resp.status_code == 400

    async def test_date_from_filter(self, client):
        ac, session, _user = client
        resp = await ac.get("/api/v1/export/missions?date_from=2026-01-01")
        assert resp.status_code == 200
        # Verify execute was called (filter applied)
        session.execute.assert_awaited_once()

    async def test_date_to_filter(self, client):
        ac, session, _user = client
        resp = await ac.get("/api/v1/export/missions?date_to=2026-12-31")
        assert resp.status_code == 200
        session.execute.assert_awaited_once()

    async def test_invalid_date_from(self, client):
        ac, _session, _user = client
        resp = await ac.get("/api/v1/export/missions?date_from=not-a-date")
        assert resp.status_code == 422

    async def test_invalid_date_to(self, client):
        ac, _session, _user = client
        resp = await ac.get("/api/v1/export/missions?date_to=not-a-date")
        assert resp.status_code == 422

    async def test_csv_injection_in_export(self, client):
        """Ensure CSV injection chars are sanitized in CSV output."""
        ac, session, _user = client
        row = _make_row("findings", title="=cmd('calc')")
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [row]
        session.execute = AsyncMock(return_value=mock_result)

        resp = await ac.get("/api/v1/export/findings?format=csv")
        assert resp.status_code == 200
        # The title column should be sanitized - starts with quote prefix
        reader = csv.reader(StringIO(resp.text))
        next(reader)  # skip header
        data_row = next(reader)
        title_idx = 2  # title is 3rd column in findings
        assert data_row[title_idx].startswith("'"), "CSV injection char should be prefixed with quote"

    async def test_content_disposition_json(self, client):
        ac, _session, _user = client
        resp = await ac.get("/api/v1/export/targets?format=json")
        assert "attachment" in resp.headers.get("content-disposition", "")
        assert "spectra_targets.json" in resp.headers.get("content-disposition", "")

    async def test_content_disposition_csv(self, client):
        ac, _session, _user = client
        resp = await ac.get("/api/v1/export/exploits?format=csv")
        assert "attachment" in resp.headers.get("content-disposition", "")
        assert "spectra_exploits.csv" in resp.headers.get("content-disposition", "")

    async def test_all_entity_types_accepted(self, client):
        ac, _session, _user = client
        for entity in _VALID_ENTITIES:
            resp = await ac.get(f"/api/v1/export/{entity}")
            assert resp.status_code == 200, f"Entity {entity} should be accepted"


@pytest.mark.asyncio
class TestExportAuth:
    """Tests for export authentication."""

    async def test_unauthenticated_returns_error(self):
        """Without auth override, the endpoint requires a token."""
        app = _make_app()
        # No dependency overrides → auth will fail
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/export/missions")
            # Should be 401 or 403 (no valid token)
            assert resp.status_code in (401, 403, 422)
