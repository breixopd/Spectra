"""Integration test for the full mission HTTP API lifecycle.

Exercises the mission endpoints (create → get → findings → stop → delete)
through the FastAPI ASGI transport with mocked backend services.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from tests.conftest import make_mock_mission

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
]

# ---- Helpers ---------------------------------------------------------------

_MISSIONS_URL = "/api/v1/missions"


def _mission_response_fields(mid: str, *, status: str = "created") -> dict:
    """Build the dict that ``MissionResponse`` expects from the manager."""
    return {
        "id": mid,
        "target": "10.0.0.1",
        "status": status,
        "current_phase": None,
        "logs": ["Starting mission"],
        "directive": "Full security assessment",
        "findings": [],
        "findings_count": 0,
        "tools_run": [],
        "tool_executions": [],
        "report_path": None,
        "attack_surface": None,
    }


# ---- Tests -----------------------------------------------------------------


class TestMissionLifecycleAPI:
    """Test the complete mission CRUD lifecycle via HTTP."""

    @pytest.fixture(autouse=True)
    def _setup_auth(self, _override_auth):
        """Ensure auth override is active for every test in this class."""

    async def test_create_mission(self, client: AsyncClient, auth_headers: dict):
        """POST /api/v1/missions should create a mission and return 200."""
        mock_mission = make_mock_mission(target="10.0.0.1", status="created")
        mid = mock_mission.id

        with (
            patch("app.api.routers.missions.mission_manager") as mm,
            patch("app.api.routers.missions.audit_log_event", new_callable=AsyncMock),
        ):
            mm.start_mission = AsyncMock(return_value=mid)
            mm.get_mission = AsyncMock(return_value=mock_mission)

            resp = await client.post(
                _MISSIONS_URL,
                json={"target": "10.0.0.1", "directive": "Full security assessment"},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == mid
        assert data["target"] == "10.0.0.1"
        assert data["status"] == "created"

    async def test_get_mission(self, client: AsyncClient, auth_headers: dict):
        """GET /api/v1/missions/{id} should return the mission."""
        mock_mission = make_mock_mission(target="10.0.0.1", status="running")
        mid = mock_mission.id

        with patch("app.api.routers.missions.mission_manager") as mm:
            mm.get_mission = AsyncMock(return_value=mock_mission)

            resp = await client.get(f"{_MISSIONS_URL}/{mid}", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == mid
        assert data["status"] == "running"

    async def test_get_mission_not_found(self, client: AsyncClient, auth_headers: dict):
        """GET /api/v1/missions/{id} returns 404 for unknown missions."""
        with patch("app.api.routers.missions.mission_manager") as mm:
            mm.get_mission = AsyncMock(return_value=None)
            # Also mock the DB fallback
            with patch("app.api.routers.missions.MissionRepository") as repo_cls:
                repo_inst = AsyncMock()
                repo_inst.get_by_id = AsyncMock(return_value=None)
                repo_cls.return_value = repo_inst

                resp = await client.get(f"{_MISSIONS_URL}/nonexistent-id", headers=auth_headers)

        assert resp.status_code == 404

    async def test_stop_mission(self, client: AsyncClient, auth_headers: dict):
        """POST /api/v1/missions/{id}/stop should stop a running mission."""
        mock_mission = make_mock_mission(status="running")
        mid = mock_mission.id

        with patch("app.api.routers.missions.mission_manager") as mm:
            mm.get_mission = AsyncMock(return_value=mock_mission)
            mm.stop_mission = AsyncMock(return_value=True)

            resp = await client.post(f"{_MISSIONS_URL}/{mid}/stop", headers=auth_headers)

        assert resp.status_code == 200
        assert resp.json()["message"] == "Mission stopping"

    async def test_stop_mission_not_found(self, client: AsyncClient, auth_headers: dict):
        """POST /api/v1/missions/{id}/stop returns 404 for unknown missions."""
        with patch("app.api.routers.missions.mission_manager") as mm:
            mm.get_mission = AsyncMock(return_value=None)
            mm.stop_mission = AsyncMock(return_value=False)

            resp = await client.post(f"{_MISSIONS_URL}/nonexistent-id/stop", headers=auth_headers)

        assert resp.status_code == 404

    async def test_get_findings_empty(self, client: AsyncClient, auth_headers: dict):
        """GET /api/v1/missions/{id}/findings returns empty list for fresh mission."""
        db_mission = MagicMock()
        db_mission.id = "test-id"
        db_mission.summary = {"findings": []}
        db_mission.user_id = None

        with patch("app.api.routers.missions.MissionRepository") as repo_cls:
            repo_inst = AsyncMock()
            repo_inst.get_by_id = AsyncMock(return_value=db_mission)
            repo_cls.return_value = repo_inst

            resp = await client.get(f"{_MISSIONS_URL}/test-id/findings", headers=auth_headers)

        assert resp.status_code == 200
        assert resp.json() == []

    async def test_get_findings_with_data(self, client: AsyncClient, auth_headers: dict):
        """GET /api/v1/missions/{id}/findings returns findings list."""
        db_mission = MagicMock()
        db_mission.id = "test-id"
        db_mission.summary = {
            "findings": [
                {
                    "title": "Open SSH Port",
                    "severity": "medium",
                    "status": "confirmed",
                    "description": "Port 22 open",
                    "tool_source": "nmap",
                    "created_at": "2026-01-01T00:00:00Z",
                },
            ]
        }
        db_mission.user_id = None

        with patch("app.api.routers.missions.MissionRepository") as repo_cls:
            repo_inst = AsyncMock()
            repo_inst.get_by_id = AsyncMock(return_value=db_mission)
            repo_cls.return_value = repo_inst

            resp = await client.get(f"{_MISSIONS_URL}/test-id/findings", headers=auth_headers)

        assert resp.status_code == 200
        findings = resp.json()
        assert len(findings) == 1
        assert findings[0]["title"] == "Open SSH Port"
        assert findings[0]["severity"] == "medium"

    async def test_pause_and_resume_mission(self, client: AsyncClient, auth_headers: dict):
        """POST pause then resume should both succeed."""
        mock_mission = make_mock_mission(status="running")
        mid = mock_mission.id

        with patch("app.api.routers.missions.mission_manager") as mm:
            mm.get_mission = AsyncMock(return_value=mock_mission)
            mm.pause_mission = AsyncMock(return_value=True)
            mm.resume_mission = AsyncMock(return_value=True)

            pause_resp = await client.post(f"{_MISSIONS_URL}/{mid}/pause", headers=auth_headers)
            assert pause_resp.status_code == 200
            assert pause_resp.json()["message"] == "Mission paused"

            resume_resp = await client.post(f"{_MISSIONS_URL}/{mid}/resume", headers=auth_headers)
            assert resume_resp.status_code == 200
            assert resume_resp.json()["message"] == "Mission resumed"

    async def test_full_lifecycle(self, client: AsyncClient, auth_headers: dict):
        """End-to-end: create → get → findings → stop."""
        mock_mission = make_mock_mission(target="10.0.0.1", status="created")
        mid = mock_mission.id

        # --- 1. Create ---
        with (
            patch("app.api.routers.missions.mission_manager") as mm,
            patch("app.api.routers.missions.audit_log_event", new_callable=AsyncMock),
        ):
            mm.start_mission = AsyncMock(return_value=mid)
            mm.get_mission = AsyncMock(return_value=mock_mission)

            create_resp = await client.post(
                _MISSIONS_URL,
                json={"target": "10.0.0.1", "directive": "Full security assessment"},
                headers=auth_headers,
            )
        assert create_resp.status_code == 200
        assert create_resp.json()["id"] == mid

        # --- 2. Get ---
        mock_mission.status = "running"
        with patch("app.api.routers.missions.mission_manager") as mm:
            mm.get_mission = AsyncMock(return_value=mock_mission)

            get_resp = await client.get(f"{_MISSIONS_URL}/{mid}", headers=auth_headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["status"] == "running"

        # --- 3. Findings ---
        db_mission = MagicMock()
        db_mission.id = mid
        db_mission.summary = {"findings": [{"title": "Test Finding", "severity": "high"}]}
        db_mission.user_id = None

        with patch("app.api.routers.missions.MissionRepository") as repo_cls:
            repo_inst = AsyncMock()
            repo_inst.get_by_id = AsyncMock(return_value=db_mission)
            repo_cls.return_value = repo_inst

            findings_resp = await client.get(f"{_MISSIONS_URL}/{mid}/findings", headers=auth_headers)
        assert findings_resp.status_code == 200
        assert len(findings_resp.json()) == 1

        # --- 4. Stop ---
        with patch("app.api.routers.missions.mission_manager") as mm:
            mm.get_mission = AsyncMock(return_value=mock_mission)
            mm.stop_mission = AsyncMock(return_value=True)

            stop_resp = await client.post(f"{_MISSIONS_URL}/{mid}/stop", headers=auth_headers)
        assert stop_resp.status_code == 200
        assert stop_resp.json()["message"] == "Mission stopping"


class TestMissionAuthEdgeCases:
    """Test auth/permission edge cases for mission endpoints."""

    async def test_create_mission_without_auth_returns_401(self, client: AsyncClient):
        """POST /api/v1/missions without auth header → 401."""
        resp = await client.post(
            _MISSIONS_URL,
            json={"target": "10.0.0.1"},
        )
        assert resp.status_code == 401

    async def test_stop_mission_without_auth_returns_401(self, client: AsyncClient):
        """POST /api/v1/missions/{id}/stop without auth → 401."""
        resp = await client.post(f"{_MISSIONS_URL}/some-id/stop")
        assert resp.status_code == 401
