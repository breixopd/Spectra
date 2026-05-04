"""Tests for plugin access control."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_user(user_id="user-1", is_superuser=False, role="user"):
    u = MagicMock()
    u.id = user_id
    u.is_superuser = is_superuser
    u.role = role
    u.is_active = True
    u.username = "testuser"
    return u


def _template_args(mock_templates):
    args = mock_templates.TemplateResponse.call_args[0]
    if isinstance(args[0], str):
        return args[0], args[1]
    return args[1], args[2]


# ---------------------------------------------------------------------------
# Plugin upload requires superuser
# ---------------------------------------------------------------------------


class TestPluginUploadAccess:
    """upload_plugin endpoint uses Depends(get_current_superuser)."""

    def test_upload_endpoint_requires_superuser_dependency(self):
        """Verify the upload_plugin route has get_current_superuser in its dependencies."""
        from spectra_api.api.routers.tools import router

        upload_routes = [r for r in router.routes if getattr(r, "path", "").rstrip("/").endswith("/upload")]
        assert upload_routes, "No /upload route found"

        route = upload_routes[0]
        dep_names = [getattr(d.call, "__name__", str(d.call)) for d in route.dependant.dependencies]  # type: ignore[union-attr]
        assert "get_current_superuser" in dep_names


# ---------------------------------------------------------------------------
# Toolbox page passes is_admin flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestToolboxPageAccess:
    """Toolbox page passes is_admin to the template context."""

    async def test_toolbox_passes_is_admin_true_for_admin(self):
        from spectra_api.ui.pages import toolbox_page

        admin_user = _make_user(is_superuser=True)

        request = MagicMock()
        request.cookies = {"access_token": "valid-token"}

        with (
            patch("spectra_api.ui.pages.get_ui_user", return_value={"sub": "admin"}),
            patch("spectra_api.ui.pages.async_session_maker") as mock_sm,
            patch("spectra_api.ui.pages._is_admin_user", return_value=True),
            patch("spectra_api.ui.pages.templates") as mock_templates,
        ):
            # Mock session context manager
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = admin_user
            mock_session.execute = AsyncMock(return_value=mock_result)

            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_session)
            ctx.__aexit__ = AsyncMock(return_value=False)
            mock_sm.return_value = ctx

            mock_templates.TemplateResponse.return_value = MagicMock()

            await toolbox_page(request)

            _, context = _template_args(mock_templates)
            assert context.get("is_admin") is True

    async def test_toolbox_passes_is_admin_false_for_operator(self):
        from spectra_api.ui.pages import toolbox_page

        operator_user = _make_user(is_superuser=False, role="user")

        request = MagicMock()
        request.cookies = {"access_token": "valid-token"}

        with (
            patch("spectra_api.ui.pages.get_ui_user", return_value={"sub": "user"}),
            patch("spectra_api.ui.pages.async_session_maker") as mock_sm,
            patch("spectra_api.ui.pages._is_admin_user", return_value=False),
            patch("spectra_api.ui.pages.templates") as mock_templates,
        ):
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = operator_user
            mock_session.execute = AsyncMock(return_value=mock_result)

            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_session)
            ctx.__aexit__ = AsyncMock(return_value=False)
            mock_sm.return_value = ctx

            mock_templates.TemplateResponse.return_value = MagicMock()

            await toolbox_page(request)

            _, context = _template_args(mock_templates)
            assert context.get("is_admin") is False


# ---------------------------------------------------------------------------
# Plugin creator page — admin gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPluginCreatorAccess:
    """plugin_creator_page redirects non-admin users."""

    async def test_non_admin_redirected_to_toolbox(self):
        from fastapi.responses import RedirectResponse

        from spectra_api.ui.pages import plugin_creator_page

        request = MagicMock()

        with (
            patch("spectra_api.ui.pages.get_ui_user", return_value={"sub": "user"}),
            patch("spectra_api.ui.pages.async_session_maker") as mock_sm,
            patch("spectra_api.ui.pages._is_admin_user", return_value=False),
        ):
            mock_session = AsyncMock()
            mock_result = MagicMock()
            non_admin = _make_user(is_superuser=False, role="user")
            mock_result.scalar_one_or_none.return_value = non_admin
            mock_session.execute = AsyncMock(return_value=mock_result)

            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_session)
            ctx.__aexit__ = AsyncMock(return_value=False)
            mock_sm.return_value = ctx

            resp = await plugin_creator_page(request)

            assert isinstance(resp, RedirectResponse)
            assert resp.status_code == 303
            assert "/toolbox" in resp.headers.get("location", "")

    async def test_admin_sees_creator_page(self):
        from spectra_api.ui.pages import plugin_creator_page

        request = MagicMock()

        with (
            patch("spectra_api.ui.pages.get_ui_user", return_value={"sub": "admin"}),
            patch("spectra_api.ui.pages.async_session_maker") as mock_sm,
            patch("spectra_api.ui.pages._is_admin_user", return_value=True),
            patch("spectra_api.ui.pages.templates") as mock_templates,
        ):
            mock_session = AsyncMock()
            mock_result = MagicMock()
            admin_user = _make_user(is_superuser=True)
            mock_result.scalar_one_or_none.return_value = admin_user
            mock_session.execute = AsyncMock(return_value=mock_result)

            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_session)
            ctx.__aexit__ = AsyncMock(return_value=False)
            mock_sm.return_value = ctx

            mock_templates.TemplateResponse.return_value = MagicMock()

            await plugin_creator_page(request)

            mock_templates.TemplateResponse.assert_called_once()
            tpl_name, _ = _template_args(mock_templates)
            assert tpl_name == "plugin_creator.html"

    async def test_unauthenticated_redirected_to_login(self):
        from fastapi.responses import RedirectResponse

        from spectra_api.ui.pages import plugin_creator_page

        request = MagicMock()

        with patch("spectra_api.ui.pages.get_ui_user", return_value=None):
            resp = await plugin_creator_page(request)

            assert isinstance(resp, RedirectResponse)
            assert resp.status_code == 303
            assert "/login" in resp.headers.get("location", "")


# ---------------------------------------------------------------------------
# Plugin list (read) accessible to regular users
# ---------------------------------------------------------------------------


class TestPluginReadAccess:
    """Regular users can list plugins (get_current_active_user, not superuser)."""

    def test_list_tools_endpoint_does_not_require_superuser(self):
        """The GET /api/v1/tools/ route uses get_current_active_user, not get_current_superuser."""
        from spectra_api.api.routers.tools import router

        # The route path is "/tools" (prefix) with path "" → full path "/tools"
        list_routes = [
            r
            for r in router.routes
            if "GET" in getattr(r, "methods", set()) and getattr(r, "path", "").rstrip("/") in ("", "/tools")
        ]
        assert list_routes, "No GET /api/v1/tools route found"

        route = list_routes[0]
        dep_names = [getattr(d.call, "__name__", str(d.call)) for d in route.dependant.dependencies]  # type: ignore[union-attr]
        assert "get_current_superuser" not in dep_names
