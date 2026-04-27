"""Tests for API docs and help UI routes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.routing import Route


def _template_call_context(mock_templates) -> tuple[str, dict]:
    args = mock_templates.TemplateResponse.call_args[0]
    if isinstance(args[0], str):
        return args[0], args[1]
    return args[1], args[2]


class TestApiDocsRoute:
    """GET /docs/api returns documentation page."""

    @pytest.mark.asyncio
    async def test_docs_api_returns_200_when_authenticated(self):
        from app.api.routers.ui import api_docs_page

        mock_request = MagicMock()

        mock_app = MagicMock()
        mock_route = MagicMock(spec=Route)
        mock_route.methods = {"GET"}
        mock_route.path = "/api/v1/health"
        mock_route.name = "health_check"
        mock_route.endpoint = MagicMock(__doc__="Health check")
        mock_route.tags = []
        mock_route.dependant = MagicMock(path_params=[], query_params=[])
        mock_app.routes = [mock_route]

        with (
            patch("app.api.routers.ui.get_ui_user", return_value={"id": 1, "username": "admin", "sub": "admin"}),
            patch(
                "app.api.routers.ui._get_ui_db_user",
                new_callable=AsyncMock,
                return_value=MagicMock(role="admin", is_superuser=True),
            ),
            patch("app.api.routers.ui._is_admin_user", return_value=True),
        ):
            with patch("app.api.routers.ui.templates") as mock_templates:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_templates.TemplateResponse.return_value = mock_response

                with patch("app.main.app", mock_app):
                    result = await api_docs_page(mock_request)

                assert result.status_code == 200
                mock_templates.TemplateResponse.assert_called_once()
                template_name, context = _template_call_context(mock_templates)
                assert template_name == "docs.html"
                assert "route_groups" in context
                assert "request" in context

    @pytest.mark.asyncio
    async def test_docs_api_redirects_when_unauthenticated(self):
        from app.api.routers.ui import api_docs_page

        mock_request = MagicMock()

        with patch("app.api.routers.ui.get_ui_user", return_value=None):
            result = await api_docs_page(mock_request)
            assert result.status_code == 303
            assert "/login" in str(result.headers.get("location", ""))

    @pytest.mark.asyncio
    async def test_docs_page_groups_routes_by_path_segment(self):
        from app.api.routers.ui import api_docs_page

        mock_request = MagicMock()

        mock_route1 = MagicMock(spec=Route)
        mock_route1.methods = {"GET"}
        mock_route1.path = "/api/v1/health"
        mock_route1.name = "health_check"
        mock_route1.endpoint = MagicMock(__doc__="Health check endpoint")
        mock_route1.tags = []
        mock_route1.dependant = MagicMock(path_params=[], query_params=[])

        mock_route2 = MagicMock(spec=Route)
        mock_route2.methods = {"GET"}
        mock_route2.path = "/api/admin/users"
        mock_route2.name = "list_users"
        mock_route2.endpoint = MagicMock(__doc__="List users")
        mock_route2.tags = []
        mock_route2.dependant = MagicMock(path_params=[], query_params=[])

        mock_app = MagicMock()
        mock_app.routes = [mock_route1, mock_route2]

        with (
            patch("app.api.routers.ui.get_ui_user", return_value={"id": 1, "role": "admin", "sub": "admin"}),
            patch(
                "app.api.routers.ui._get_ui_db_user",
                new_callable=AsyncMock,
                return_value=MagicMock(role="admin", is_superuser=True),
            ),
            patch("app.api.routers.ui._is_admin_user", return_value=True),
            patch("app.api.routers.ui.require_feature", return_value=MagicMock(role="admin", is_superuser=True)),
            patch("app.api.routers.ui.templates") as mock_templates,
            patch("app.main.app", mock_app),
        ):
            mock_templates.TemplateResponse.return_value = MagicMock(status_code=200)
            await api_docs_page(mock_request)

            _, context = _template_call_context(mock_templates)
            groups = context["route_groups"]
            assert "v1" in groups
            assert "admin" in groups

    @pytest.mark.asyncio
    async def test_docs_page_hides_admin_routes_for_non_admin(self):
        """Non-admin users should not see admin route groups."""
        from app.api.routers.ui import api_docs_page

        mock_request = MagicMock()

        mock_route1 = MagicMock(spec=Route)
        mock_route1.methods = {"GET"}
        mock_route1.path = "/api/v1/health"
        mock_route1.name = "health_check"
        mock_route1.endpoint = MagicMock(__doc__="Health check endpoint")
        mock_route1.tags = []
        mock_route1.dependant = MagicMock(path_params=[], query_params=[])

        mock_route2 = MagicMock(spec=Route)
        mock_route2.methods = {"GET"}
        mock_route2.path = "/api/admin/users"
        mock_route2.name = "list_users"
        mock_route2.endpoint = MagicMock(__doc__="List users")
        mock_route2.tags = []
        mock_route2.dependant = MagicMock(path_params=[], query_params=[])

        mock_app = MagicMock()
        mock_app.routes = [mock_route1, mock_route2]

        with (
            patch("app.api.routers.ui.get_ui_user", return_value={"id": 1, "role": "user", "sub": "user"}),
            patch(
                "app.api.routers.ui._get_ui_db_user",
                new_callable=AsyncMock,
                return_value=MagicMock(role="user", is_superuser=False),
            ),
            patch("app.api.routers.ui._is_admin_user", return_value=False),
            patch("app.api.routers.ui.require_feature", return_value=MagicMock(role="user", is_superuser=False)),
            patch("app.api.routers.ui.templates") as mock_templates,
            patch("app.main.app", mock_app),
        ):
            mock_templates.TemplateResponse.return_value = MagicMock(status_code=200)
            await api_docs_page(mock_request)

            _, context = _template_call_context(mock_templates)
            groups = context["route_groups"]
            assert "v1" in groups
            assert "admin" not in groups


class TestHelpRoute:
    """GET /help returns help page."""

    @pytest.mark.asyncio
    async def test_help_returns_200_when_authenticated(self):
        from app.api.routers.ui import help_page

        mock_request = MagicMock()

        with patch("app.api.routers.ui.get_ui_user", return_value={"id": 1, "username": "admin"}):
            with patch("app.api.routers.ui.templates") as mock_templates:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_templates.TemplateResponse.return_value = mock_response

                result = await help_page(mock_request)

                assert result.status_code == 200
                mock_templates.TemplateResponse.assert_called_once()
                template_name, _ = _template_call_context(mock_templates)
                assert template_name == "help.html"

    @pytest.mark.asyncio
    async def test_help_redirects_when_unauthenticated(self):
        from app.api.routers.ui import help_page

        mock_request = MagicMock()

        with patch("app.api.routers.ui.get_ui_user", return_value=None):
            result = await help_page(mock_request)
            assert result.status_code == 303
