"""
Tests for public-facing routes.

Covers:
- /api/v1/system/public-status returns a JSON response without authentication
- Legacy /api/public/forgot-password and /api/public/reset-password POST
  endpoints are not registered (they were removed)
- HTML pages /status, /security, and /changelog are registered
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _openapi_paths() -> set[str]:
    """Use FastAPI's generated contract instead of its internal router tree."""
    from spectra_api.main import app

    return set(app.openapi()["paths"])


# ---------------------------------------------------------------------------
# Public system status API
# ---------------------------------------------------------------------------


class TestPublicStatusApi:
    """GET /api/v1/system/public-status works without authentication."""

    @pytest.mark.asyncio
    async def test_public_status_returns_operational_when_db_healthy(self):
        from unittest.mock import patch

        from spectra_api.api.routers.system.health import get_public_system_status

        with patch(
            "spectra_api.api.routers.system.health.collect_platform_health", new_callable=AsyncMock
        ) as mock_health:
            mock_health.return_value = {
                "status": "healthy",
                "version": "1.0.0",
                "timestamp": "2024-01-01T00:00:00Z",
                "components": {"database": {"status": "healthy"}},
                "services": {"api": {"status": "healthy"}},
            }
            mock_session = AsyncMock()
            result = await get_public_system_status(session=mock_session)

        assert result["status"] == "operational"
        assert "database" in result
        assert result["database"]["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_public_status_returns_degraded_when_db_fails(self):
        from spectra_api.api.routers.system.health import get_public_system_status

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=Exception("DB down"))

        result = await get_public_system_status(session=mock_session)

        assert result["status"] == "degraded"
        assert result["database"]["status"] == "unhealthy"

    def test_public_status_route_has_no_auth_dependency(self):
        """The public-status route must not require get_current_active_user."""
        import inspect

        from spectra_api.api.dependencies import get_current_active_user
        from spectra_api.api.routers.system.health import get_public_system_status

        dep_callables = [
            getattr(parameter.default, "dependency", None)
            for parameter in inspect.signature(get_public_system_status).parameters.values()
        ]
        assert get_current_active_user not in dep_callables


# ---------------------------------------------------------------------------
# Deleted legacy endpoints
# ---------------------------------------------------------------------------


class TestDeletedPublicApiEndpoints:
    """Former /api/public/* password-reset API endpoints are not registered."""

    def test_api_public_forgot_password_not_registered(self):
        all_paths = _openapi_paths()
        assert "/api/public/forgot-password" not in all_paths, (
            "/api/public/forgot-password should not be registered as an API endpoint"
        )

    def test_api_public_reset_password_not_registered(self):
        all_paths = _openapi_paths()
        assert "/api/public/reset-password" not in all_paths, (
            "/api/public/reset-password should not be registered as an API endpoint"
        )


# ---------------------------------------------------------------------------
# HTML page routes exist
# ---------------------------------------------------------------------------


class TestPublicPageRoutes:
    """HTML pages /status, /security, and /changelog are registered."""

    def test_status_page_route_registered(self):
        from spectra_api.main import app

        assert str(app.url_path_for("status_page")) == "/status"

    def test_security_page_route_registered(self):
        from spectra_api.main import app

        assert str(app.url_path_for("security_page")) == "/security"

    def test_changelog_page_route_registered(self):
        from spectra_api.main import app

        assert str(app.url_path_for("changelog_page")) == "/changelog"

    @pytest.mark.asyncio
    async def test_status_page_renders_without_auth(self):
        from starlette.requests import Request

        from spectra_api.ui.public import status_page

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/status",
            "headers": [],
            "query_string": b"",
        }
        request = Request(scope)

        with patch("spectra_api.ui.public.templates") as mock_tmpl:
            mock_tmpl.TemplateResponse.return_value = MagicMock(status_code=200)
            resp = await status_page(request)

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_security_page_renders_without_auth(self):
        from starlette.requests import Request

        from spectra_api.ui.public import security_page

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/security",
            "headers": [],
            "query_string": b"",
        }
        request = Request(scope)

        with patch("spectra_api.ui.public.templates") as mock_tmpl:
            mock_tmpl.TemplateResponse.return_value = MagicMock(status_code=200)
            resp = await security_page(request)

        assert resp.status_code == 200
