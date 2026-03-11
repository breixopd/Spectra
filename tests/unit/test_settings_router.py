"""Tests for settings API endpoints (GET/POST /api/settings in ui.py)."""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers.ui import router
from app.models.user import User


def _make_user(is_superuser: bool = False, username: str = "testuser") -> User:
    user = MagicMock(spec=User)
    user.id = "u-1"
    user.username = username
    user.is_superuser = is_superuser
    user.is_active = True
    user.role = "admin" if is_superuser else "operator"
    return user


def _build_app(current_user: User | None = None):
    """Build a minimal FastAPI app with the UI router and auth overrides."""
    from app.api.dependencies import get_current_active_user
    from app.core.rbac import require_permission

    app = FastAPI()
    app.include_router(router)

    if current_user is not None:
        app.dependency_overrides[get_current_active_user] = lambda: current_user
        # Override every require_permission call to just return the user
        for perm in ("manage_settings",):
            dep = require_permission(perm)
            if current_user.is_superuser:
                app.dependency_overrides[dep] = lambda: current_user

    return app


class TestGetSettings:
    @patch("app.api.routers.ui.get_current_settings")
    def test_get_settings_authenticated(self, mock_get):
        mock_get.return_value = {"ai_provider": "mock", "log_level": "DEBUG"}
        user = _make_user(is_superuser=True)
        app = _build_app(user)
        client = TestClient(app)

        resp = client.get("/api/settings")

        assert resp.status_code == 200
        assert resp.json()["ai_provider"] == "mock"

    def test_get_settings_unauthenticated(self):
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        resp = client.get("/api/settings")

        assert resp.status_code in (401, 403)


class TestUpdateSettings:
    @patch("app.api.routers.ui.apply_settings_update", new_callable=AsyncMock)
    @patch("app.api.routers.ui.get_async_session")
    def test_superuser_can_update(self, mock_session, mock_apply):
        mock_apply.return_value = {"status": "updated", "message": "Settings updated and saved"}
        mock_db = AsyncMock()
        mock_session.return_value = mock_db

        user = _make_user(is_superuser=True)
        from app.api.dependencies import get_current_active_user
        from app.core.database import get_async_session as real_get_session
        from app.core.rbac import Permission, require_permission

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_active_user] = lambda: user
        app.dependency_overrides[real_get_session] = lambda: mock_db
        # Override the specific permission dependency
        dep = require_permission(Permission.MANAGE_SETTINGS)
        app.dependency_overrides[dep] = lambda: user

        client = TestClient(app)
        resp = client.post("/api/settings", json={"log_level": "WARNING"})

        assert resp.status_code == 200
        assert resp.json()["status"] == "updated"

    def test_non_superuser_cannot_update(self):
        """Non-superuser should be rejected by the permission check."""
        user = _make_user(is_superuser=False)
        from app.api.dependencies import get_current_active_user

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_active_user] = lambda: user

        client = TestClient(app)
        resp = client.post("/api/settings", json={"log_level": "WARNING"})

        # Should fail because require_permission(MANAGE_SETTINGS) is not overridden
        assert resp.status_code in (401, 403)


class TestSettingsValidation:
    @patch("app.api.routers.ui.apply_settings_update", new_callable=AsyncMock)
    def test_invalid_ai_provider_rejected(self, mock_apply):
        user = _make_user(is_superuser=True)
        from app.api.dependencies import get_current_active_user
        from app.core.database import get_async_session as real_get_session
        from app.core.rbac import Permission, require_permission

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_active_user] = lambda: user
        app.dependency_overrides[real_get_session] = lambda: AsyncMock()
        dep = require_permission(Permission.MANAGE_SETTINGS)
        app.dependency_overrides[dep] = lambda: user

        client = TestClient(app)
        resp = client.post("/api/settings", json={"ai_provider": "not_a_valid_provider"})

        # Pydantic validation should reject the value (pattern mismatch)
        assert resp.status_code == 422

    @patch("app.api.routers.ui.apply_settings_update", new_callable=AsyncMock)
    def test_invalid_log_level_rejected(self, mock_apply):
        user = _make_user(is_superuser=True)
        from app.api.dependencies import get_current_active_user
        from app.core.database import get_async_session as real_get_session
        from app.core.rbac import Permission, require_permission

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_active_user] = lambda: user
        app.dependency_overrides[real_get_session] = lambda: AsyncMock()
        dep = require_permission(Permission.MANAGE_SETTINGS)
        app.dependency_overrides[dep] = lambda: user

        client = TestClient(app)
        resp = client.post("/api/settings", json={"log_level": "INVALID_LEVEL"})

        assert resp.status_code == 422
