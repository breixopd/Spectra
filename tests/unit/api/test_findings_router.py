"""Tests for the findings API router."""

import csv
from datetime import datetime
from io import StringIO
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routers.findings import router
from app.core.enums import Severity
from app.models.finding import FindingStatus


def _fake_user(is_superuser: bool = False, user_id: str = "00000000-0000-4000-a000-000000000001", role: str = "user"):
    user = MagicMock()
    user.id = user_id
    user.is_superuser = is_superuser
    user.role = role
    return user


def _fake_finding(**overrides):
    defaults = {
        "id": "00000000-0000-4000-a000-f00000000001",
        "target_id": "00000000-0000-4000-a000-100000000001",
        "title": "SQL Injection",
        "description": "Parameterised query missing",
        "severity": Severity.HIGH,
        "status": FindingStatus.POTENTIAL,
        "cvss_score": 8.5,
        "cve_id": "CVE-2026-0001",
        "tool_source": "sqlmap",
        "evidence": {"payload": "' OR 1=1--"},
        "user_id": "00000000-0000-4000-a000-000000000001",
        "created_at": datetime(2026, 1, 1, 12, 0),
    }
    defaults.update(overrides)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_app() -> FastAPI:
    from app.core.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    limiter.enabled = False
    app.include_router(router, prefix="/api/v1/findings")
    return app


@pytest_asyncio.fixture
async def client():
    app = _make_app()
    from app.api.dependencies import get_current_active_user
    from app.core.database import get_async_session

    user = _fake_user()
    app.dependency_overrides[get_current_active_user] = lambda: user

    mock_session = AsyncMock()
    mock_session.add = MagicMock()  # sync method
    mock_session.commit = AsyncMock()

    async def _get_session():
        yield mock_session

    app.dependency_overrides[get_async_session] = _get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, mock_session, user


@pytest_asyncio.fixture
async def unauth_client():
    """Client with no auth override — dependency raises 401."""
    app = _make_app()
    from app.core.database import get_async_session

    mock_session = AsyncMock()
    mock_session.add = MagicMock()  # sync method

    async def _get_session():
        yield mock_session

    app.dependency_overrides[get_async_session] = _get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# List findings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListFindings:
    async def test_list_findings_empty(self, client):
        ac, _session, _user = client
        from app.repositories.finding import FindingRepository

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(FindingRepository, "count", AsyncMock(return_value=0))
            mp.setattr(FindingRepository, "find_many_by", AsyncMock(return_value=[]))
            resp = await ac.get("/api/v1/findings")

        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_list_findings_with_data(self, client):
        ac, _session, _user = client
        from app.repositories.finding import FindingRepository

        finding = _fake_finding()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(FindingRepository, "count", AsyncMock(return_value=1))
            mp.setattr(FindingRepository, "find_many_by", AsyncMock(return_value=[finding]))
            resp = await ac.get("/api/v1/findings")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["title"] == "SQL Injection"

    async def test_list_findings_pagination(self, client):
        ac, _session, _user = client
        from app.repositories.finding import FindingRepository

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(FindingRepository, "count", AsyncMock(return_value=50))
            mp.setattr(FindingRepository, "find_many_by", AsyncMock(return_value=[]))
            resp = await ac.get("/api/v1/findings?page=2&per_page=10")

        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 2
        assert data["per_page"] == 10
        assert data["total"] == 50


# ---------------------------------------------------------------------------
# Get single finding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetFinding:
    async def test_get_finding_success(self, client):
        ac, _session, _user = client
        from app.repositories.finding import FindingRepository

        finding = _fake_finding()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(FindingRepository, "get_by_id", AsyncMock(return_value=finding))
            resp = await ac.get("/api/v1/findings/00000000-0000-4000-a000-f00000000001")

        assert resp.status_code == 200
        assert resp.json()["id"] == "00000000-0000-4000-a000-f00000000001"
        assert resp.json()["severity"] == "high"

    async def test_get_finding_not_found(self, client):
        ac, _session, _user = client
        from app.repositories.finding import FindingRepository

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(FindingRepository, "get_by_id", AsyncMock(return_value=None))
            resp = await ac.get("/api/v1/findings/00000000-0000-4000-a000-f00000000099")

        assert resp.status_code == 404

    async def test_get_finding_forbidden(self, client):
        ac, _session, _user = client
        from app.repositories.finding import FindingRepository

        finding = _fake_finding(user_id="00000000-0000-4000-a000-000000000099")
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(FindingRepository, "get_by_id", AsyncMock(return_value=finding))
            resp = await ac.get("/api/v1/findings/00000000-0000-4000-a000-f00000000001")

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Create finding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCreateFinding:
    async def test_create_finding_valid(self, client):
        ac, _session, _user = client
        from app.repositories.finding import FindingRepository

        finding = _fake_finding()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(FindingRepository, "create", AsyncMock(return_value=finding))
            resp = await ac.post(
                "/api/v1/findings",
                json={
                    "target_id": "t-1",
                    "title": "SQL Injection",
                    "severity": "high",
                    "tool_source": "sqlmap",
                },
            )

        assert resp.status_code == 201
        assert resp.json()["title"] == "SQL Injection"

    async def test_create_finding_missing_fields(self, client):
        ac, _session, _user = client
        resp = await ac.post("/api/v1/findings", json={"title": "incomplete"})
        assert resp.status_code == 422

    async def test_create_finding_rejects_oversized_evidence_map(self, client):
        ac, _session, _user = client
        resp = await ac.post(
            "/api/v1/findings",
            json={
                "target_id": "t-1",
                "title": "SQL Injection",
                "severity": "high",
                "tool_source": "sqlmap",
                "evidence": {f"k{i}": "value" for i in range(26)},
            },
        )
        assert resp.status_code == 422

    async def test_create_finding_rejects_oversized_evidence_value(self, client):
        ac, _session, _user = client
        resp = await ac.post(
            "/api/v1/findings",
            json={
                "target_id": "t-1",
                "title": "SQL Injection",
                "severity": "high",
                "tool_source": "sqlmap",
                "evidence": {"request": "x" * 5001},
            },
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Update finding (PATCH)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestUpdateFinding:
    async def test_update_finding_success(self, client):
        ac, _session, _user = client
        from app.repositories.finding import FindingRepository

        existing = _fake_finding()
        updated = _fake_finding(title="Updated Title")
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(FindingRepository, "get_by_id", AsyncMock(return_value=existing))
            mp.setattr(FindingRepository, "update", AsyncMock(return_value=updated))
            resp = await ac.patch(
                "/api/v1/findings/00000000-0000-4000-a000-f00000000001",
                json={"title": "Updated Title"},
            )

        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated Title"

    async def test_update_finding_not_found(self, client):
        ac, _session, _user = client
        from app.repositories.finding import FindingRepository

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(FindingRepository, "get_by_id", AsyncMock(return_value=None))
            resp = await ac.patch(
                "/api/v1/findings/00000000-0000-4000-a000-f00000000099",
                json={"title": "x"},
            )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Delete finding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDeleteFinding:
    async def test_delete_finding_success(self, client):
        ac, _session, _user = client
        from app.repositories.finding import FindingRepository

        finding = _fake_finding()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(FindingRepository, "get_by_id", AsyncMock(return_value=finding))
            mp.setattr(FindingRepository, "delete", AsyncMock(return_value=None))
            resp = await ac.delete("/api/v1/findings/00000000-0000-4000-a000-f00000000001")

        assert resp.status_code == 204

    async def test_delete_finding_not_found(self, client):
        ac, _session, _user = client
        from app.repositories.finding import FindingRepository

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(FindingRepository, "get_by_id", AsyncMock(return_value=None))
            resp = await ac.delete("/api/v1/findings/00000000-0000-4000-a000-f00000000099")

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Export and status helper paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFindingExportsAndStatusPaths:
    async def test_export_csv_preserves_zero_cvss_score(self, client):
        ac, _session, _user = client
        from app.repositories.finding import FindingRepository

        finding = _fake_finding(cvss_score=0.0)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(FindingRepository, "find_many_by", AsyncMock(return_value=[finding]))
            resp = await ac.get("/api/v1/findings/export/csv")

        assert resp.status_code == 200
        rows = list(csv.DictReader(StringIO(resp.text)))
        assert rows[0]["cvss_score"] == "0.0"

    async def test_export_csv_encrypted_requires_password_header(self, client):
        ac, _session, _user = client
        from app.repositories.finding import FindingRepository

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(FindingRepository, "find_many_by", AsyncMock(return_value=[]))
            resp = await ac.get("/api/v1/findings/export/csv?encrypted=true")

        assert resp.status_code == 400
        assert resp.json()["detail"] == "X-Export-Password header required when encrypted=true"

    async def test_export_json_sets_media_type_and_filename(self, client):
        ac, _session, _user = client
        from app.repositories.finding import FindingRepository

        finding = _fake_finding()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(FindingRepository, "find_many_by", AsyncMock(return_value=[finding]))
            resp = await ac.get("/api/v1/findings/export/json")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        assert resp.headers["content-disposition"] == "attachment; filename=spectra_findings.json"
        assert resp.json()[0]["id"] == finding.id

    async def test_export_json_encrypted_sets_encrypted_headers(self, client):
        ac, _session, _user = client
        from app.repositories.finding import FindingRepository

        with pytest.MonkeyPatch.context() as mp:
            encrypt = MagicMock(return_value=b"encrypted-payload")
            mp.setattr(FindingRepository, "find_many_by", AsyncMock(return_value=[]))
            mp.setattr("app.core.encryption.encrypt_data_with_password", encrypt)
            resp = await ac.get(
                "/api/v1/findings/export/json?encrypted=true",
                headers={"X-Export-Password": "secret-pass"},
            )

        assert resp.status_code == 200
        assert resp.content == b"encrypted-payload"
        assert resp.headers["content-type"].startswith("application/octet-stream")
        assert resp.headers["content-disposition"] == "attachment; filename=spectra_findings.json.enc"
        encrypt.assert_called_once()

    async def test_verify_finding_returns_explicit_500_when_update_is_falsy(self, client):
        ac, _session, _user = client
        from app.repositories.finding import FindingRepository

        finding = _fake_finding()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(FindingRepository, "get_by_id", AsyncMock(return_value=finding))
            mp.setattr(FindingRepository, "update", AsyncMock(return_value=None))
            resp = await ac.post("/api/v1/findings/00000000-0000-4000-a000-f00000000001/verify")

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Update failed unexpectedly"

    async def test_confirm_finding_keeps_generic_500_when_update_is_falsy(self):
        app = _make_app()
        from app.api.dependencies import get_current_active_user
        from app.core.database import get_async_session
        from app.repositories.finding import FindingRepository

        user = _fake_user()
        app.dependency_overrides[get_current_active_user] = lambda: user

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        async def _get_session():
            yield mock_session

        app.dependency_overrides[get_async_session] = _get_session

        finding = _fake_finding()
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(FindingRepository, "get_by_id", AsyncMock(return_value=finding))
                mp.setattr(FindingRepository, "update", AsyncMock(return_value=None))
                resp = await ac.post("/api/v1/findings/00000000-0000-4000-a000-f00000000001/confirm")

        assert resp.status_code == 500
        assert resp.text == "Internal Server Error"


# ---------------------------------------------------------------------------
# Auth: 401 without token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFindingsAuth:
    async def test_list_findings_no_auth(self, unauth_client):
        resp = await unauth_client.get("/api/v1/findings")
        assert resp.status_code == 401

    async def test_get_finding_no_auth(self, unauth_client):
        resp = await unauth_client.get("/api/v1/findings/00000000-0000-4000-a000-f00000000001")
        assert resp.status_code == 401

    async def test_create_finding_no_auth(self, unauth_client):
        resp = await unauth_client.post("/api/v1/findings", json={"title": "x"})
        assert resp.status_code == 401

    async def test_delete_finding_no_auth(self, unauth_client):
        resp = await unauth_client.delete("/api/v1/findings/00000000-0000-4000-a000-f00000000001")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Rate-limit decorator is present on list endpoint
# ---------------------------------------------------------------------------


class TestRateLimitDecorator:
    def test_list_findings_has_rate_limit(self):
        from app.api.routers.findings import list_findings

        # slowapi wraps the function and adds _rate_limits
        assert hasattr(list_findings, "__wrapped__") or hasattr(list_findings, "_rate_limits"), (
            "list_findings should have a rate-limit decorator"
        )
