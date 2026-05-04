"""Tests verifying that key operations emit the correct audit events."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_user(role: str = "admin", user_id: str = "00000000-0000-4000-a000-000000000001", username: str = "testuser"):
    user = MagicMock()
    user.id = user_id
    user.username = username
    user.is_superuser = role == "admin"
    user.role = role
    user.is_active = True
    user.mfa_enabled = True
    user.mfa_secret = "encrypted-secret"
    user.hashed_password = "hashed"
    user.invalidated_before = None
    return user


def _override_deps(app: FastAPI, user, mock_session):
    from spectra_api.api.dependencies import get_current_active_user
    from spectra_platform.core.database import get_async_session

    app.dependency_overrides[get_current_active_user] = lambda: user

    async def _get_session():
        yield mock_session

    app.dependency_overrides[get_async_session] = _get_session


def _make_app_with_router(router, prefix: str = ""):
    from spectra_platform.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    limiter.enabled = False
    app.include_router(router, prefix=prefix)
    return app


# ---------------------------------------------------------------------------
# 1. Logout emits LOGOUT audit event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLogoutAuditEmission:
    async def test_logout_emits_audit_event(self):
        from spectra_api.api.routers.auth import router

        app = _make_app_with_router(router, prefix="/auth")
        user = _fake_user()
        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        _override_deps(app, user, mock_session)

        token_payload = {"sub": user.username, "exp": 9999999999}

        with (
            patch("spectra_api.api.routers.auth.login._extract_bearer_token", return_value="fake-token"),
            patch("spectra_api.api.routers.auth.login._decode_token_or_http_error", return_value=token_payload),
            patch("spectra_api.api.routers.auth.login.invalidate_token"),
            patch("spectra_api.api.routers.auth.login._get_user_by_username", new_callable=AsyncMock, return_value=user),
            patch("spectra_api.api.routers.auth.login._clear_auth_cookies"),
            patch("spectra_api.api.routers.auth.login.audit_log_event", new_callable=AsyncMock) as mock_audit,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.post(
                    "/auth/logout",
                    headers={"Authorization": "Bearer fake-token"},
                )

            assert resp.status_code == 200
            mock_audit.assert_called_once()
            call_args = mock_audit.call_args
            from spectra_platform.models.audit_log import AuditEventType

            assert call_args[0][1] == AuditEventType.LOGOUT
            assert call_args[1]["user_id"] == str(user.id)


# ---------------------------------------------------------------------------
# 2. Mission stop emits MISSION_STATUS_CHANGED audit event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMissionStopAuditEmission:
    async def test_mission_stop_emits_audit_event(self):
        from spectra_api.api.routers.missions import router

        app = _make_app_with_router(router, prefix="/missions")
        user = _fake_user()
        mock_session = AsyncMock()
        _override_deps(app, user, mock_session)

        mission_id = "00000000-0000-4000-a000-000000000123"
        fake_mission = MagicMock()
        fake_mission.user_id = user.id

        with (
            patch("spectra_api.api.routers.missions.mission_lifecycle.MissionRepository") as mock_repo_cls,
            patch("spectra_api.api.routers.missions.mission_lifecycle.mission_manager") as mock_mm,
            patch("spectra_api.api.routers.missions.mission_lifecycle.audit_log_event", new_callable=AsyncMock) as mock_audit,
            patch("spectra_api.api.routers.missions.mission_lifecycle.check_resource_owner"),
        ):
            mock_repo_cls.return_value.get_by_id = AsyncMock(return_value=fake_mission)
            mock_mm.stop_mission = AsyncMock(return_value=True)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.post(f"/missions/{mission_id}/stop")

            assert resp.status_code == 200
            mock_audit.assert_called_once()
            call_args = mock_audit.call_args
            from spectra_platform.models.audit_log import AuditEventType

            assert call_args[0][1] == AuditEventType.MISSION_STATUS_CHANGED
            assert call_args[1]["details"]["action"] == "stopped"
            assert call_args[1]["details"]["mission_id"] == mission_id


# ---------------------------------------------------------------------------
# 3. Mission pause emits MISSION_STATUS_CHANGED audit event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMissionPauseAuditEmission:
    async def test_mission_pause_emits_audit_event(self):
        from spectra_api.api.routers.missions import router

        app = _make_app_with_router(router, prefix="/missions")
        user = _fake_user()
        mock_session = AsyncMock()
        _override_deps(app, user, mock_session)

        mission_id = "00000000-0000-4000-a000-000000000456"
        fake_mission = MagicMock()
        fake_mission.user_id = user.id

        with (
            patch("spectra_api.api.routers.missions.mission_lifecycle.MissionRepository") as mock_repo_cls,
            patch("spectra_api.api.routers.missions.mission_lifecycle.mission_manager") as mock_mm,
            patch("spectra_api.api.routers.missions.mission_lifecycle.audit_log_event", new_callable=AsyncMock) as mock_audit,
            patch("spectra_api.api.routers.missions.mission_lifecycle.check_resource_owner"),
        ):
            mock_repo_cls.return_value.get_by_id = AsyncMock(return_value=fake_mission)
            mock_mm.pause_mission = AsyncMock(return_value=True)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.post(f"/missions/{mission_id}/pause")

            assert resp.status_code == 200
            mock_audit.assert_called_once()
            call_args = mock_audit.call_args
            from spectra_platform.models.audit_log import AuditEventType

            assert call_args[0][1] == AuditEventType.MISSION_STATUS_CHANGED
            assert call_args[1]["details"]["action"] == "paused"
            assert call_args[1]["details"]["mission_id"] == mission_id


# ---------------------------------------------------------------------------
# 4. Failed MFA emits LOGIN_FAILED audit event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFailedMfaAuditEmission:
    async def test_failed_mfa_emits_audit_event(self):
        from spectra_api.api.routers.auth import router

        app = _make_app_with_router(router, prefix="/auth")
        user = _fake_user()
        mock_session = AsyncMock()
        _override_deps(app, user, mock_session)

        mfa_payload = {"sub": user.username, "mfa_pending": True, "exp": 9999999999}

        with (
            patch("spectra_api.api.routers.auth.totp._extract_bearer_token", return_value="mfa-token"),
            patch(
                "spectra_api.api.routers.auth.totp._decode_token_or_http_error",
                new=AsyncMock(return_value=mfa_payload),
            ),
            patch("spectra_api.api.routers.auth.totp._get_user_by_username", new_callable=AsyncMock, return_value=user),
            patch("spectra_api.api.routers.auth.totp._check_lockout", new_callable=AsyncMock, return_value=None),
            patch("spectra_api.api.routers.auth.totp._record_failure", new_callable=AsyncMock, return_value=None),
            patch("spectra_api.api.routers.auth.totp.decrypt_mfa_secret", return_value="raw-secret"),
            patch("spectra_api.api.routers.auth.totp.verify_totp", return_value=False),
            patch("spectra_api.api.routers.auth.totp.audit_log_event", new_callable=AsyncMock) as mock_audit,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.post(
                    "/auth/mfa/verify",
                    json={"code": "000000"},
                    headers={"Authorization": "Bearer mfa-token"},
                )

            assert resp.status_code == 401
            mock_audit.assert_called_once()
            call_args = mock_audit.call_args
            from spectra_platform.models.audit_log import AuditEventType

            assert call_args[0][1] == AuditEventType.LOGIN_FAILED
            assert call_args[1]["details"]["reason"] == "mfa_failed"


# ---------------------------------------------------------------------------
# 5. Findings CSV export emits audit event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFindingsExportAuditEmission:
    async def test_findings_export_csv_emits_audit_event(self):
        from spectra_api.api.routers.findings import router

        app = _make_app_with_router(router, prefix="/findings")
        user = _fake_user()
        mock_session = AsyncMock()
        _override_deps(app, user, mock_session)

        with (
            patch("spectra_api.api.routers.findings.bulk._fetch_all_findings", new_callable=AsyncMock, return_value=[]),
            patch("spectra_api.api.routers.findings.bulk.audit_log_event", new_callable=AsyncMock) as mock_audit,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/findings/export/csv")

            assert resp.status_code == 200
            mock_audit.assert_called_once()
            call_args = mock_audit.call_args
            assert call_args[1]["details"]["action"] == "findings_exported"
            assert call_args[1]["details"]["format"] == "csv"


# ---------------------------------------------------------------------------
# 6. Audit-logs endpoint accepts ip_address filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAuditIpAddressFilter:
    async def test_ip_address_filter_in_audit_api(self):
        from spectra_api.api.routers.admin.audit import router

        app = _make_app_with_router(router)
        user = _fake_user(role="admin")
        mock_session = AsyncMock()

        fake_row = MagicMock()
        fake_row.id = "a-1"
        fake_row.user_id = "u-1"
        fake_row.event_type = "LOGIN"
        fake_row.details = "{}"
        fake_row.ip_address = "10.0.0.42"
        fake_row.created_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

        user_lookup = MagicMock()
        user_lookup.all.return_value = []
        mock_session.execute = AsyncMock(return_value=user_lookup)

        with patch("spectra_api.api.routers.admin.audit.AuditLogRepository") as MockRepo:
            repo_inst = MockRepo.return_value
            repo_inst.count_events = AsyncMock(return_value=1)
            repo_inst.list_events = AsyncMock(return_value=[fake_row])

            _override_deps(app, user, mock_session)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/admin/audit-logs?ip_address=10.0.0.42")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["ip_address"] == "10.0.0.42"

        # Verify ip_address was passed through to the repository
        repo_inst.count_events.assert_called_once()
        count_kwargs = repo_inst.count_events.call_args[1]
        assert count_kwargs["ip_address"] == "10.0.0.42"
