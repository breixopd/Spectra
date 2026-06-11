"""Tests for plugin access control."""


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
