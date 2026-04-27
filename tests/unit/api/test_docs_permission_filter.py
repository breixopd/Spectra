"""
Tests for API docs permission filtering.

Complements test_api_docs_route.py with additional coverage of:
- Admin users see all route groups including the admin group
- Non-admin users (viewer role) cannot see the admin route group
- Route group keys are determined by the second URL segment
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.routing import Route


def _make_mock_route(path: str, name: str = "endpoint"):
    route = MagicMock(spec=Route)
    route.methods = {"GET"}
    route.path = path
    route.name = name
    route.endpoint = MagicMock(__doc__="A mock endpoint")
    route.tags = []
    route.dependant = MagicMock(path_params=[], query_params=[])
    return route


def _mock_app_with_routes(routes):
    app = MagicMock()
    app.routes = routes
    return app


def _template_context(mock_tmpl):
    args = mock_tmpl.TemplateResponse.call_args[0]
    return args[1] if isinstance(args[0], str) else args[2]


class TestDocsAdminVisibility:
    """Admin users see admin route groups; non-admins do not."""

    @pytest.mark.asyncio
    async def test_admin_sees_admin_route_group(self):
        from app.api.routers.ui import api_docs_page

        mock_routes = [
            _make_mock_route("/api/v1/health", "health_check"),
            _make_mock_route("/api/admin/users", "list_users"),
        ]

        with (
            patch("app.api.routers.ui.get_ui_user", return_value={"id": 1, "role": "admin", "sub": "admin"}),
            patch(
                "app.api.routers.ui._get_ui_db_user",
                new_callable=AsyncMock,
                return_value=MagicMock(role="admin", is_superuser=True),
            ),
            patch("app.api.routers.ui._is_admin_user", return_value=True),
            patch("app.api.routers.ui.require_feature", return_value=MagicMock(role="admin", is_superuser=True)),
            patch("app.api.routers.ui.templates") as mock_tmpl,
            patch("app.main.app", _mock_app_with_routes(mock_routes)),
        ):
            mock_tmpl.TemplateResponse.return_value = MagicMock(status_code=200)
            await api_docs_page(MagicMock())

        context = _template_context(mock_tmpl)
        groups = context["route_groups"]
        assert "admin" in groups, "Admin user should see the admin route group"

    @pytest.mark.asyncio
    async def test_operator_does_not_see_admin_route_group(self):
        from app.api.routers.ui import api_docs_page

        mock_routes = [
            _make_mock_route("/api/v1/health", "health_check"),
            _make_mock_route("/api/admin/users", "list_users"),
        ]

        with (
            patch("app.api.routers.ui.get_ui_user", return_value={"id": 1, "role": "user", "sub": "user"}),
            patch(
                "app.api.routers.ui._get_ui_db_user",
                new_callable=AsyncMock,
                return_value=MagicMock(role="user", is_superuser=False),
            ),
            patch("app.api.routers.ui._is_admin_user", return_value=False),
            patch("app.api.routers.ui.require_feature", return_value=MagicMock(role="user", is_superuser=False)),
            patch("app.api.routers.ui.templates") as mock_tmpl,
            patch("app.main.app", _mock_app_with_routes(mock_routes)),
        ):
            mock_tmpl.TemplateResponse.return_value = MagicMock(status_code=200)
            await api_docs_page(MagicMock())

        context = _template_context(mock_tmpl)
        groups = context["route_groups"]
        assert "admin" not in groups, "Operator should not see admin route group"
        assert "v1" in groups, "Operator should still see /api/v1/* routes"

    @pytest.mark.asyncio
    async def test_viewer_does_not_see_admin_route_group(self):
        from app.api.routers.ui import api_docs_page

        mock_routes = [
            _make_mock_route("/api/v1/findings", "list_findings"),
            _make_mock_route("/api/admin/settings", "admin_settings"),
        ]

        with (
            patch("app.api.routers.ui.get_ui_user", return_value={"id": 2, "role": "staff", "sub": "staff"}),
            patch(
                "app.api.routers.ui._get_ui_db_user",
                new_callable=AsyncMock,
                return_value=MagicMock(role="staff", is_superuser=False),
            ),
            patch("app.api.routers.ui._is_admin_user", return_value=False),
            patch("app.api.routers.ui.require_feature", return_value=MagicMock(role="staff", is_superuser=False)),
            patch("app.api.routers.ui.templates") as mock_tmpl,
            patch("app.main.app", _mock_app_with_routes(mock_routes)),
        ):
            mock_tmpl.TemplateResponse.return_value = MagicMock(status_code=200)
            await api_docs_page(MagicMock())

        context = _template_context(mock_tmpl)
        groups = context["route_groups"]
        assert "admin" not in groups

    @pytest.mark.asyncio
    async def test_admin_sees_all_route_groups(self):
        """Admin can see both /api/v1/* and /api/admin/* groups simultaneously."""
        from app.api.routers.ui import api_docs_page

        mock_routes = [
            _make_mock_route("/api/v1/missions", "list_missions"),
            _make_mock_route("/api/v1/targets", "list_targets"),
            _make_mock_route("/api/admin/users", "list_users"),
            _make_mock_route("/api/admin/audit-logs", "list_audit_logs"),
        ]

        with (
            patch("app.api.routers.ui.get_ui_user", return_value={"id": 1, "role": "admin", "sub": "admin"}),
            patch(
                "app.api.routers.ui._get_ui_db_user",
                new_callable=AsyncMock,
                return_value=MagicMock(role="admin", is_superuser=True),
            ),
            patch("app.api.routers.ui._is_admin_user", return_value=True),
            patch("app.api.routers.ui.require_feature", return_value=MagicMock(role="admin", is_superuser=True)),
            patch("app.api.routers.ui.templates") as mock_tmpl,
            patch("app.main.app", _mock_app_with_routes(mock_routes)),
        ):
            mock_tmpl.TemplateResponse.return_value = MagicMock(status_code=200)
            await api_docs_page(MagicMock())

        context = _template_context(mock_tmpl)
        groups = context["route_groups"]
        assert "v1" in groups
        assert "admin" in groups

    @pytest.mark.asyncio
    async def test_unauthenticated_redirects_to_login(self):
        """Unauthenticated request to /docs/api redirects to /login."""
        from app.api.routers.ui import api_docs_page

        with (
            patch("app.api.routers.ui.get_ui_user", return_value=None),
            patch("app.api.routers.ui._is_admin_user", return_value=False),
        ):
            result = await api_docs_page(MagicMock())

        assert result.status_code == 303
        assert "/login" in str(result.headers.get("location", ""))
