"""Tests for user settings / preferences API."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(user_id="user-1", is_superuser=False, role="operator", plan_id=None):
    u = MagicMock()
    u.id = user_id
    u.is_superuser = is_superuser
    u.role = role
    u.is_active = True
    u.plan_id = plan_id
    return u


def _make_request():
    """Return a mock Request with client info."""
    req = MagicMock()
    req.client = MagicMock()
    req.client.host = "127.0.0.1"
    req.headers = {"user-agent": "test"}
    return req


def _make_prefs(**overrides):
    """Return a mock UserPreferences row."""
    defaults = dict(
        user_id="user-1",
        llm_api_key=None,
        llm_api_base_url=None,
        llm_model=None,
        embedding_api_key=None,
        embedding_api_base_url=None,
        embedding_model=None,
        email_notifications=True,
        webhook_url=None,
        notify_on_mission_complete=True,
        notify_on_critical_finding=True,
        default_scan_mode="autonomous",
        default_report_format="pdf",
        timezone="UTC",
    )
    defaults.update(overrides)
    m = MagicMock(**defaults)
    # Ensure attribute access works
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


# ---------------------------------------------------------------------------
# _prefs_to_response
# ---------------------------------------------------------------------------

class TestPrefsToResponse:
    def test_none_returns_defaults(self):
        from app.api.routers.user_settings import _prefs_to_response

        resp = _prefs_to_response(None)
        assert resp.llm_api_key_configured is False
        assert resp.embedding_api_key_configured is False
        assert resp.email_notifications is True
        assert resp.default_scan_mode == "autonomous"
        assert resp.timezone == "UTC"

    def test_masks_api_keys(self):
        from app.api.routers.user_settings import _prefs_to_response

        prefs = _make_prefs(llm_api_key="sk-secret-123", embedding_api_key="sk-embed-456")
        resp = _prefs_to_response(prefs)
        assert resp.llm_api_key_configured is True
        assert resp.embedding_api_key_configured is True
        # The actual key should NEVER appear in the response
        resp_dict = resp.model_dump()
        assert "sk-secret-123" not in str(resp_dict)
        assert "sk-embed-456" not in str(resp_dict)

    def test_no_keys_shows_not_configured(self):
        from app.api.routers.user_settings import _prefs_to_response

        prefs = _make_prefs(llm_api_key=None, embedding_api_key=None)
        resp = _prefs_to_response(prefs)
        assert resp.llm_api_key_configured is False
        assert resp.embedding_api_key_configured is False

    def test_preserves_other_fields(self):
        from app.api.routers.user_settings import _prefs_to_response

        prefs = _make_prefs(
            webhook_url="https://hooks.example.com/x",
            default_scan_mode="guided",
            timezone="US/Eastern",
        )
        resp = _prefs_to_response(prefs)
        assert resp.webhook_url == "https://hooks.example.com/x"
        assert resp.default_scan_mode == "guided"
        assert resp.timezone == "US/Eastern"


# ---------------------------------------------------------------------------
# GET /api/v1/user/settings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestGetUserSettings:
    async def test_returns_defaults_when_no_prefs(self):
        from app.api.routers.user_settings import get_user_settings

        user = _make_user()
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        resp = await get_user_settings(user=user, session=session)
        assert resp.llm_api_key_configured is False
        assert resp.email_notifications is True
        assert resp.timezone == "UTC"

    async def test_returns_existing_prefs(self):
        from app.api.routers.user_settings import get_user_settings

        user = _make_user()
        prefs = _make_prefs(llm_api_key="sk-key", timezone="Europe/Berlin")
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = prefs
        session.execute = AsyncMock(return_value=result_mock)

        resp = await get_user_settings(user=user, session=session)
        assert resp.llm_api_key_configured is True
        assert resp.timezone == "Europe/Berlin"


# ---------------------------------------------------------------------------
# PUT /api/v1/user/settings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestUpdateUserSettings:
    async def test_creates_prefs_for_first_time_user(self):
        from app.api.schemas.user_settings import UserSettingsUpdate
        from app.api.routers.user_settings import update_user_settings

        user = _make_user()
        request = _make_request()
        session = AsyncMock()
        # First execute: _get_prefs returns None
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        added = []
        session.add = lambda obj: added.append(obj)

        # After commit + refresh, simulate the prefs having been created
        _make_prefs(timezone="Asia/Tokyo")
        session.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "timezone", "Asia/Tokyo") or None)

        body = UserSettingsUpdate(timezone="Asia/Tokyo")

        with patch("app.api.routers.user_settings._get_prefs", new_callable=AsyncMock, return_value=None):
            with patch("app.api.routers.user_settings.UserPreferences") as MockUP:
                instance = _make_prefs(timezone="Asia/Tokyo")
                MockUP.return_value = instance
                with patch("app.api.routers.user_settings.audit_log_event", new_callable=AsyncMock):
                    resp = await update_user_settings(body=body, request=request, user=user, session=session)
        assert resp.timezone == "Asia/Tokyo"

    async def test_updates_existing_prefs(self):
        from app.api.schemas.user_settings import UserSettingsUpdate
        from app.api.routers.user_settings import update_user_settings

        user = _make_user()
        request = _make_request()
        prefs = _make_prefs(timezone="UTC")
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = prefs
        session.execute = AsyncMock(return_value=result_mock)
        session.refresh = AsyncMock()

        body = UserSettingsUpdate(timezone="US/Pacific")
        with patch("app.api.routers.user_settings.audit_log_event", new_callable=AsyncMock):
            await update_user_settings(body=body, request=request, user=user, session=session)
        assert prefs.timezone == "US/Pacific"

    async def test_empty_body_returns_422(self):
        from app.api.schemas.user_settings import UserSettingsUpdate
        from app.api.routers.user_settings import update_user_settings

        user = _make_user()
        request = _make_request()
        session = AsyncMock()

        body = UserSettingsUpdate()
        with pytest.raises(HTTPException) as exc_info:
            await update_user_settings(body=body, request=request, user=user, session=session)
        assert exc_info.value.status_code == 422

    async def test_byok_rejected_when_plan_disallows(self):
        from app.api.schemas.user_settings import UserSettingsUpdate
        from app.api.routers.user_settings import update_user_settings

        user = _make_user(plan_id="plan-1")
        request = _make_request()
        session = AsyncMock()

        async def mock_check(u, s, feature):
            raise HTTPException(status_code=403, detail=f"Feature '{feature}' not available on your plan")

        body = UserSettingsUpdate(llm_api_key="sk-new-key")

        with patch("app.api.routers.user_settings.check_feature_allowed", side_effect=mock_check):
            with pytest.raises(HTTPException) as exc_info:
                await update_user_settings(body=body, request=request, user=user, session=session)
            assert exc_info.value.status_code == 403
            assert "byok" in exc_info.value.detail

    async def test_byok_accepted_when_plan_allows(self):
        from app.api.schemas.user_settings import UserSettingsUpdate
        from app.api.routers.user_settings import update_user_settings

        user = _make_user(plan_id="plan-pro")
        request = _make_request()
        prefs = _make_prefs()
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = prefs
        session.execute = AsyncMock(return_value=result_mock)
        session.refresh = AsyncMock()

        body = UserSettingsUpdate(llm_api_key="sk-allowed-key", llm_model="gpt-4o")

        with patch("app.api.routers.user_settings.check_feature_allowed", new_callable=AsyncMock):
            with patch("app.api.routers.user_settings.audit_log_event", new_callable=AsyncMock):
                with patch("app.api.routers.user_settings.encrypt_byok_key", side_effect=lambda k: f"enc:{k}"):
                    await update_user_settings(body=body, request=request, user=user, session=session)
        # Key should be encrypted now
        assert prefs.llm_api_key == "enc:sk-allowed-key"
        assert prefs.llm_model == "gpt-4o"

    async def test_non_byok_fields_dont_trigger_check(self):
        from app.api.schemas.user_settings import UserSettingsUpdate
        from app.api.routers.user_settings import update_user_settings

        user = _make_user(plan_id="plan-1")
        request = _make_request()
        prefs = _make_prefs()
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = prefs
        session.execute = AsyncMock(return_value=result_mock)
        session.refresh = AsyncMock()

        check_mock = AsyncMock()
        body = UserSettingsUpdate(timezone="Europe/London")

        with patch("app.api.routers.user_settings.check_feature_allowed", check_mock):
            with patch("app.api.routers.user_settings.audit_log_event", new_callable=AsyncMock):
                await update_user_settings(body=body, request=request, user=user, session=session)
        check_mock.assert_not_called()


# ---------------------------------------------------------------------------
# DELETE /api/v1/user/settings/byok
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestClearByok:
    async def test_clears_byok_fields(self):
        from app.api.routers.user_settings import clear_byok, BYOK_FIELDS

        user = _make_user()
        request = _make_request()
        prefs = _make_prefs(
            llm_api_key="sk-x", llm_api_base_url="https://api.openai.com",
            llm_model="gpt-4", embedding_api_key="sk-e",
            embedding_api_base_url="https://embed.example.com",
            embedding_model="text-embedding-3-small",
        )
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = prefs
        session.execute = AsyncMock(return_value=result_mock)

        with patch("app.api.routers.user_settings.audit_log_event", new_callable=AsyncMock):
            resp = await clear_byok(request=request, user=user, session=session)
        for field in BYOK_FIELDS:
            assert getattr(prefs, field) is None
        assert resp["detail"] == "BYOK configuration cleared"

    async def test_noop_when_no_prefs(self):
        from app.api.routers.user_settings import clear_byok

        user = _make_user()
        request = _make_request()
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)

        resp = await clear_byok(request=request, user=user, session=session)
        assert "No BYOK" in resp["detail"]


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestSchemas:
    def test_response_defaults(self):
        from app.api.schemas.user_settings import UserSettingsResponse

        r = UserSettingsResponse()
        assert r.llm_api_key_configured is False
        assert r.default_scan_mode == "autonomous"

    def test_update_partial(self):
        from app.api.schemas.user_settings import UserSettingsUpdate

        u = UserSettingsUpdate(timezone="US/Eastern")
        dumped = u.model_dump(exclude_unset=True)
        assert dumped == {"timezone": "US/Eastern"}
