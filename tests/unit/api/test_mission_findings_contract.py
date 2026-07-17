"""Contract tests for the mission-output findings API."""

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from spectra_api.api.routers.missions import router


def _fake_user():
    user = MagicMock()
    user.id = "00000000-0000-4000-a000-000000000001"
    user.is_superuser = False
    return user


@pytest_asyncio.fixture
async def client():
    from spectra_api.api.dependencies import get_current_active_user
    from spectra_persistence.database import get_async_session

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/missions")
    user = _fake_user()
    app.dependency_overrides[get_current_active_user] = lambda: user

    async def _get_session():
        yield AsyncMock()

    app.dependency_overrides[get_async_session] = _get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client, user


@pytest.mark.asyncio
async def test_mission_findings_have_durable_ids_and_normalized_evidence(client, monkeypatch):
    from spectra_persistence.repositories.mission import MissionRepository

    async_client, user = client
    mission = MagicMock()
    mission.id = "00000000-0000-4000-a000-000000000010"
    mission.user_id = user.id
    mission.summary = {
        "findings": [
            {
                "title": "Exposed admin endpoint",
                "description": "Administrative surface is publicly reachable.",
                "severity": "high",
                "status": "verified",
                "tool_source": "nuclei",
                "http_transcript": "GET /admin HTTP/1.1",
                "command": "nuclei -u https://example.test",
            }
        ]
    }
    monkeypatch.setattr(MissionRepository, "get_by_id", AsyncMock(return_value=mission))

    response = await async_client.get(f"/api/v1/missions/{mission.id}/findings")

    assert response.status_code == 200
    finding = response.json()[0]
    assert UUID(finding["id"]).version == 5
    assert finding["proof_status"] == "verified"
    assert finding["evidence_bundle"]["http_transcript"] == "GET /admin HTTP/1.1"
    assert finding["evidence_bundle"]["command"] == "nuclei -u https://example.test"


@pytest.mark.asyncio
async def test_json_export_includes_only_the_report_builder_selection(client, monkeypatch):
    """A report builder selection must reach the export payload, not just the UI."""
    from spectra_mission.output_model import get_mission_findings
    from spectra_persistence.repositories.mission import MissionRepository

    async_client, user = client
    user.is_superuser = True
    mission = MagicMock()
    mission.id = "00000000-0000-4000-a000-000000000020"
    mission.user_id = user.id
    mission.target = "example.test"
    mission.status = "completed"
    mission.directive = "Validate report selection"
    mission.created_at = None
    mission.attack_surface = {}
    mission.summary = {
        "findings": [
            {"title": "Selected", "severity": "high", "status": "verified"},
            {"title": "Excluded", "severity": "low", "status": "potential"},
        ]
    }
    selected_id = get_mission_findings(mission)[0]["id"]
    monkeypatch.setattr(MissionRepository, "get_by_id", AsyncMock(return_value=mission))
    monkeypatch.setattr(
        "spectra_api.api.routers.missions.export.audit_log_event",
        AsyncMock(),
    )

    response = await async_client.get(f"/api/v1/missions/{mission.id}/export/json?finding_id={selected_id}")

    assert response.status_code == 200
    assert [finding["title"] for finding in response.json()["findings"]] == ["Selected"]
